MaixCAM 语音关键词记录器
========================

输出文件:
  /home/jlu/桌面/config/voice_keyword_log.txt

启动:
  cd /home/jlu/桌面/config
  ./start_voice_keyword_logger.sh

停止:
  cd /home/jlu/桌面/config
  ./stop_voice_keyword_logger.sh

运行日志:
  /home/jlu/桌面/config/voice_keyword_logger.out

说明:
  - 时间使用本机时间（Asia/Shanghai）。
  - KWS 行是模型给出的关键词概率；GATE 行是实际触发灯控门。
  - 记录会持续追加，直到手动停止。
  - 脚本通过 SSH 读取 192.168.1.183:/root/surplife/pwm.log；
    断了会自动重连。
  - 依赖 voice_pwm.py 以 VOICE_KWS_DEBUG=1 运行；当前已在用。
  - 板子重启后 voice_pwm 不会自启动，需要先启动语音程序。

当前进程:
  PID 记录在 voice_keyword_logger.pid
