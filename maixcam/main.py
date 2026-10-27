"""MaixCAM-Pro: YOLO11 pose + geometry rules + HTML skeleton.

Open this folder in MaixVision and use Run Project, or run main.py alone.
An embedded HTML page is used if Run Current File does not transfer index.html.
The model and its companion binary must already be on the DEVICE.
"""
import json
import math
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL_PATH = "/root/models/yolo11n_pose.mud"
HTTP_PORT = 8080


def normalize_points(flat, width, height):
    """MaixPy returns 34 flat x/y values; unavailable coordinates are -1."""
    if len(flat) != 34:
        raise ValueError("Expected COCO 17 keypoints / 34 x,y values; use a pose model")
    points = []
    for i in range(0, 34, 2):
        x, y = float(flat[i]), float(flat[i + 1])
        valid = (math.isfinite(x) and math.isfinite(y)
                 and 0 <= x < width and 0 <= y < height)
        points.append([int(x), int(y)] if valid else None)
    return points


def joint_angle(a, b, c):
    """Angle ABC in degrees, or None for missing/degenerate joints."""
    if a is None or b is None or c is None:
        return None
    u = (a[0] - b[0], a[1] - b[1])
    v = (c[0] - b[0], c[1] - b[1])
    length = math.hypot(*u) * math.hypot(*v)
    if length < 1e-6:
        return None
    cosine = (u[0] * v[0] + u[1] * v[1]) / length
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def classify_pose(p):
    """Single-frame heuristics; these are not trained action predictions."""
    actions = []
    torso_lengths = [math.dist(p[s], p[h]) for s, h in ((5, 11), (6, 12))
                     if p[s] is not None and p[h] is not None]
    # Relative threshold scales with the person; pixels have y increasing downwards.
    margin = max(3.0, 0.15 * sum(torso_lengths) / len(torso_lengths)) if torso_lengths else 5.0

    def raised(shoulder, wrist):
        if p[shoulder] is None or p[wrist] is None:
            return None
        return p[wrist][1] < p[shoulder][1] - margin

    left, right = raised(5, 9), raised(6, 10)
    if left is True and right is True:
        actions.append("both_hands_up")
    elif left is True:
        actions.append("left_hand_up" if right is False else "left_hand_up_right_unknown")
    elif right is True:
        actions.append("right_hand_up" if left is False else "right_hand_up_left_unknown")

    # Require the whole torso and both legs, rather than guessing from an occluded leg.
    if all(p[i] is not None for i in (5, 6, 11, 12, 13, 14, 15, 16)):
        shoulder = [(p[5][j] + p[6][j]) / 2 for j in (0, 1)]
        hip = [(p[11][j] + p[12][j]) / 2 for j in (0, 1)]
        upright = hip[1] - shoulder[1] > max(3, abs(hip[0] - shoulder[0]))
        knees = [joint_angle(p[11], p[13], p[15]), joint_angle(p[12], p[14], p[16])]
        if upright and all(k is not None for k in knees):
            if min(knees) > 160:
                actions.append("standing")
            elif max(knees) < 140:
                actions.append("crouch_or_sit")
    return actions or ["unknown"]


class PoseState:
    def __init__(self, width, height):
        self.lock = threading.Lock()
        self.updated = time.monotonic()
        self.data = dict(width=width, height=height, frame_id=0, fps=0, people=[])

    def publish(self, frame_id, fps, people):
        with self.lock:
            self.data = dict(width=self.data["width"], height=self.data["height"],
                             frame_id=frame_id, fps=round(fps, 1), people=people)
            self.updated = time.monotonic()

    def snapshot(self):
        with self.lock:
            result = dict(self.data)
            result["age_ms"] = int((time.monotonic() - self.updated) * 1000)
            return result


def load_html(html_path):
    try:
        with open(html_path, "rb") as file:
            return file.read()
    except FileNotFoundError:
        return EMBEDDED_HTML.encode("utf-8")


def make_server(state, html_path, host="0.0.0.0", port=HTTP_PORT):
    html = load_html(html_path)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                payload, content_type = html, "text/html; charset=utf-8"
            elif path == "/api/pose":
                payload = json.dumps(state.snapshot(), allow_nan=False).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Browser closed this request.

        def log_message(self, fmt, *args):
            pass

    return ThreadingHTTPServer((host, port), Handler)


def main():
    # Import only on the board; geometry checks can run on an ordinary PC.
    from maix import camera, display, image, nn, app

    if not os.path.isfile(MODEL_PATH):
        raise FileNotFoundError("Set MODEL_PATH to your DEVICE's YOLO11-Pose .mud file: " + MODEL_PATH)
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    if not os.path.isfile(html_path):
        print("index.html was not transferred; using the embedded skeleton page")
    # False keeps keypoints aligned with the image currently being displayed.
    detector = nn.YOLO11(model=MODEL_PATH, dual_buff=False)
    width, height = detector.input_width(), detector.input_height()
    cam = camera.Camera(width, height, detector.input_format())
    disp = display.Display()
    state = PoseState(width, height)
    server = make_server(state, html_path)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
    thread.start()
    print("Skeleton page: http://<device-ip>:{}".format(HTTP_PORT))
    frame_id = 0
    try:
        while not app.need_exit():
            started = time.monotonic()
            img = cam.read()
            objects = detector.detect(img, conf_th=0.5, iou_th=0.45, keypoint_th=0.5)
            people = []
            for index, obj in enumerate(objects):
                points = normalize_points(obj.points, width, height)
                actions = classify_pose(points)
                people.append(dict(index=index, score=float(obj.score),
                                   bbox=[int(obj.x), int(obj.y), int(obj.w), int(obj.h)],
                                   points=points, actions=actions))
                img.draw_rect(obj.x, obj.y, obj.w, obj.h, color=image.COLOR_GREEN)
                detector.draw_pose(img, obj.points, 4, image.COLOR_GREEN)
                img.draw_string(max(0, obj.x), max(0, obj.y), " / ".join(actions), color=image.COLOR_GREEN)
            disp.show(img)  # Device display + MaixVision preview.
            frame_id += 1
            fps = 1.0 / max(time.monotonic() - started, 1e-6)
            state.publish(frame_id, fps, people)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


# Keep the single-file MaixVision run usable when auxiliary files are not sent.
EMBEDDED_HTML = r"""
<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MaixCAM-Pro · 人体骨骼</title>
<style>
  *{box-sizing:border-box}body{margin:0;background:#0c1524;color:#e9f2ff;font:16px system-ui,sans-serif}
  main{max-width:1060px;margin:auto;padding:32px 22px}h1{font-size:28px;margin:12px 0}p{color:#a9bad1;line-height:1.7}
  .tag{color:#70eac4;font-size:12px;letter-spacing:2px}.bar{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:24px 0}
  button,select{border:1px solid #3b526e;border-radius:8px;padding:10px 16px;background:#14263e;color:#e9f2ff;font:inherit}
  button{cursor:pointer}button:hover{border-color:#70eac4}canvas{display:block;width:100%;height:auto;background:#101e31;border:1px solid #29405b;border-radius:14px}
  #status{color:#70eac4}.cards{display:flex;flex-wrap:wrap;gap:12px;margin-top:16px}.card{padding:16px;border:1px solid #29405b;border-radius:10px;min-width:200px}
  small{color:#a9bad1}.note{font-size:13px}option{background:#14263e}
</style>
<main>
  <span class="tag">MAIXCAM-PRO / YOLO11-POSE</span>
  <h1>人体骨骼与姿态</h1>
  <p>17 个关键点连接成人体骨骼。设备负责推理，浏览器负责显示。</p>
  <div class="bar">
    <button id="live">连接设备数据</button><button id="demo">演示骨骼</button>
    <select id="pose" aria-label="演示姿态"><option value="standing">站立</option><option value="left_hand_up">举左手</option><option value="both_hands_up">举双手</option><option value="crouch_or_sit">屈膝／坐姿</option></select>
    <span id="status" role="status">演示模式 · 非摄像头数据</span>
  </div>
  <canvas id="canvas" width="960" height="672" aria-label="人体骨骼画布"></canvas>
  <div class="cards" id="people"></div>
  <p class="note">绿线：躯干与左侧肢体；蓝线：右侧肢体。左右按人体自身定义。缺失的关键点不连线。网页显示骨骼，摄像头画面与骨骼叠加可在 MaixVision 中查看。</p>
  <p class="note">实时使用：从 <code>http://设备IP:8080</code> 打开页面。直接打开 HTML 文件可看演示；屈膝与坐姿仅凭单帧无法可靠区分。人物编号仅代表当前帧的检测顺序。</p>
</main>
<script>
const canvas=document.querySelector('#canvas'),ctx=canvas.getContext('2d');
const status=document.querySelector('#status'),cards=document.querySelector('#people');
const names={standing:'站立',left_hand_up:'举左手',right_hand_up:'举右手',both_hands_up:'举双手',crouch_or_sit:'屈膝／坐姿',unknown:'姿态不确定',left_hand_up_right_unknown:'举左手 · 右手不可见',right_hand_up_left_unknown:'举右手 · 左手不可见'};
// COCO indices: head, torso, arms, legs. Never connect an unavailable point.
const edges=[[0,1],[0,2],[1,3],[2,4],[5,6],[5,11],[6,12],[11,12],[5,7],[7,9],[6,8],[8,10],[11,13],[13,15],[12,14],[14,16]];
const right=new Set([2,4,6,8,10,12,14,16]);
let mode='demo',generation=0;
function draw(data){
  const w=data.width,h=data.height,s=Math.min(canvas.width/w,canvas.height/h);
  const ox=(canvas.width-w*s)/2,oy=(canvas.height-h*s)/2;
  ctx.clearRect(0,0,canvas.width,canvas.height);
  ctx.strokeStyle='#1c304a';ctx.lineWidth=1;
  for(let x=0;x<canvas.width;x+=48){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,canvas.height);ctx.stroke();}
  for(let y=0;y<canvas.height;y+=48){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(canvas.width,y);ctx.stroke();}
  cards.replaceChildren();
  for(const person of data.people){
    const p=person.points;
    ctx.lineWidth=4;ctx.lineCap='round';
    for(const [a,b] of edges){
      if(!p[a]||!p[b])continue;
      ctx.strokeStyle=right.has(a)&&right.has(b)?'#63b5ff':'#70eac4';ctx.beginPath();
      ctx.moveTo(ox+p[a][0]*s,oy+p[a][1]*s);ctx.lineTo(ox+p[b][0]*s,oy+p[b][1]*s);ctx.stroke();
    }
    p.forEach((xy,i)=>{if(!xy)return;ctx.fillStyle=right.has(i)?'#63b5ff':'#70eac4';ctx.beginPath();ctx.arc(ox+xy[0]*s,oy+xy[1]*s,5,0,Math.PI*2);ctx.fill();});
    if(person.bbox){ctx.strokeStyle='#64819f';ctx.lineWidth=1;const [x,y,bw,bh]=person.bbox;ctx.strokeRect(ox+x*s,oy+y*s,bw*s,bh*s);}
    const card=document.createElement('div');card.className='card';
    const title=document.createElement('small');title.textContent=`人物 ${person.index+1} · 人体检测分数 ${Math.round(person.score*100)}%`;
    const label=document.createElement('p');label.textContent=person.actions.map(a=>names[a]||a).join(' / ');label.style.marginBottom='0';
    card.append(title,label);cards.append(card);
  }
  if(!data.people.length)cards.textContent='未检测到人体';
}
function demo(){
  const action=document.querySelector('#pose').value;
  const p=[[160,35],[154,30],[166,30],[146,35],[174,35],[135,70],[185,70],[125,115],[195,115],[120,150],[200,150],[140,135],[180,135],[140,170],[180,170],[140,210],[180,210]];
  if(action==='left_hand_up'||action==='both_hands_up'){p[7]=[120,40];p[9]=[120,10];}
  if(action==='both_hands_up'){p[8]=[200,40];p[10]=[200,10];}
  if(action==='crouch_or_sit'){p[13]=[115,165];p[14]=[205,165];p[15]=[145,195];p[16]=[175,195];}
  draw({width:320,height:224,people:[{index:0,score:1,bbox:[100,5,120,215],points:p,actions:[action]}]});
  status.textContent='演示模式 · 非摄像头数据';
}
async function poll(token){
  if(mode!=='live'||token!==generation)return;
  try{
    const response=await fetch('/api/pose',{cache:'no-store',signal:AbortSignal.timeout(3000)});
    if(!response.ok)throw new Error(`HTTP ${response.status}`);
    const data=await response.json();
    if(mode!=='live'||token!==generation)return;
    if(data.age_ms>3000){draw({...data,people:[]});status.textContent='设备数据已超过 3 秒未更新';}
    else{draw(data);status.textContent=`实时 · ${data.fps} FPS · 帧 ${data.frame_id}`;}
  }catch(error){
    if(mode!=='live'||token!==generation)return;
    draw({width:320,height:224,people:[]});status.textContent=`连接失败：${error.message}`;
  }
  if(mode==='live'&&token===generation)setTimeout(()=>poll(token),100);
}
document.querySelector('#live').onclick=()=>{
  if(location.protocol==='file:'){status.textContent='请从 http://设备IP:8080 打开此页面后连接';return;}
  mode='live';generation++;status.textContent='正在连接设备…';poll(generation);
};
document.querySelector('#demo').onclick=()=>{mode='demo';generation++;demo();};
document.querySelector('#pose').onchange=()=>{mode='demo';generation++;demo();};
demo();
if(location.protocol==='http:'||location.protocol==='https:')document.querySelector('#live').click();
</script>
</html>
""".lstrip("\n")


if __name__ == "__main__":
    main()
