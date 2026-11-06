import numpy as np
from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import JSONResponse, StreamingResponse
from contextlib import asynccontextmanager
from typing import List, Optional
import logging
import json
import configparser
from SenseVoiceAx import SenseVoiceAx
import os
import soxr
import asyncio
import time

# 初始化日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 全局变量存储模型
asr_model = None
asr_model_is_loaded = False
mud_configs = None


def parse_config_file_to_json(file_path):
    """从文件读取配置并解析为JSON"""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"配置文件不存在: {file_path}")

    config = configparser.ConfigParser()
    config.read(file_path, encoding='utf-8')

    result = {}
    for section in config.sections():
        result[section] = {}
        for key, value in config[section].items():
            # 简单类型转换
            value = value.strip()

            if value.lower() == 'true':
                result[section][key] = True
            elif value.lower() == 'false':
                result[section][key] = False
            elif value.lower() == 'none' or value == '':
                result[section][key] = None
            elif value.isdigit():
                result[section][key] = int(value)
            else:
                result[section][key] = value

    return result

g_heartbeat = False
g_heartbeat_lock = asyncio.Lock()

async def set_heartbeat(en: bool):
    global g_heartbeat
    global headbeat_lock
    await g_heartbeat_lock.acquire()
    try:
        g_heartbeat = en
    finally:
        g_heartbeat_lock.release()

async def try_stop_model():
    global asr_model
    global asr_model_is_loaded
    del asr_model
    asr_model = None
    asr_model_is_loaded = False

async def handle_heartbeat():
    global asr_model_is_loaded
    global g_heartbeat
    global g_heartbeat_lock
    last_get_heartbeat_s = time.time()
    """
    定期检查连接状态，清理断开的连接
    """
    while True:
        if asr_model_is_loaded:
            await g_heartbeat_lock.acquire()
            try:
                print("Check heartbeat:", g_heartbeat)
                if not g_heartbeat:
                    if time.time() - last_get_heartbeat_s > 30:    # 30秒内没有心跳则认为连接断开, 尝试释放模型
                        print("Check heartbeat timeout, try release model")
                        await try_stop_model()
                else:
                    last_get_heartbeat_s = time.time()

                g_heartbeat = False
            finally:
                g_heartbeat_lock.release()
        else:
            last_get_heartbeat_s = time.time() # 模型未加载时，重置获取心跳的时间
        await asyncio.sleep(10)  # 每隔 10 秒检查一次

@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(handle_heartbeat())
    yield

app = FastAPI(title="ASR Server", lifespan = lifespan, description="Automatic Speech Recognition API")

def validate_audio_data(audio_data: List[float]) -> np.ndarray:
    """
    验证并转换音频数据为numpy数组

    参数:
    - audio_data: 浮点数列表表示的音频数据

    返回:
    - 验证后的numpy数组
    """
    try:
        # 转换为numpy数组
        np_array = np.array(audio_data, dtype=np.float32)

        # 验证数据有效性
        if np_array.ndim != 1:
            raise ValueError("Audio data must be 1-dimensional")

        if len(np_array) == 0:
            raise ValueError("Audio data cannot be empty")

        return np_array
    except Exception as e:
        raise ValueError(f"Invalid audio data: {str(e)}")


@app.get("/heartbeat", summary="Update heartbeat")
async def heartbeat():
    await set_heartbeat(True)
    return JSONResponse(content={"satus": "ok"})

@app.get("/get_language", summary="Get current language")
async def get_language():
    return JSONResponse(content={"language": asr_model.language})

@app.get(
    "/get_language_options",
    summary="Get possible language options, possible options include [auto, zh, en, yue, ja, ko]",
)
async def get_language_options():
    return JSONResponse(content={"language_options": asr_model.language_options})

@app.get("/status", summary="Get ASR model status")
async def get_status():
    global asr_model_is_loaded
    return JSONResponse(content={"status": "loaded" if asr_model_is_loaded else "not loaded"})

@app.post("/reset_model", summary="Reset model")
async def reset_model():
    global asr_model
    global asr_model_is_loaded
    if not asr_model_is_loaded:
        return JSONResponse(content={"status": "not loaded"})
    asr_model.reset()
    return JSONResponse(content={"status": "ok"})

@app.post("/start_model", summary="Load model")
async def start_model(
    model_path: str = Body(
        "sensevoice_ax630c/sensevoice.axmodel",
        description="Path to the model file",
    ),
    language: str = Body("auto", description="Language"),
    stream: bool = Body(False, description="streaming or not"),
):
    """
    服务启动时加载ASR模型
    """
    global asr_model
    global asr_model_is_loaded

    if asr_model_is_loaded:
        if asr_model.streaming == stream:
            return JSONResponse(content={"status": "loaded"})
        else:
            await try_stop_model()

    logger.info("Loading ASR model...")

    try:
        mud_configs = parse_config_file_to_json(model_path)
        axmodel_path = mud_configs.get("basic", {}).get("model_npu", None)
        streaming_axmodel_path = mud_configs.get("extra", {}).get("stream_model", None)
        model_dir_path = os.path.dirname(model_path)
        if stream:
            if streaming_axmodel_path is None:
                logger.error(f"Not found model:{streaming_axmodel_path}")
                raise HTTPException(status_code=400, detail=f"Not found model:{streaming_axmodel_path}")
            model_path = os.path.join(model_dir_path, streaming_axmodel_path)
        else:
            if axmodel_path is None:
                logger.error(f"Not found model:{axmodel_path}")
                raise HTTPException(status_code=400, detail=f"Not found model:{axmodel_path}")
            model_path = os.path.join(model_dir_path, axmodel_path)

        # 模型加载
        use_itn = mud_configs.get("extra", {}).get("use_itn", True)  # 逆文本规范
        beam_size = mud_configs.get("extra", {}).get("beam_size", 3)
        hot_words = mud_configs.get("extra", {}).get("hot_words", None)
        use_itn = mud_configs.get("extra", {}).get("use_itn", True)
        streaming = stream
        max_len = 26 if streaming else 256

        print(f'model path: {model_path}')
        print(f'max_len: {max_len}')
        print(f'beam_size: {beam_size}')
        print(f"language: {language}")
        print(f'hot_words: {hot_words}')
        print(f"use_itn: {use_itn}")
        print(f'streaming: {streaming}')

        if not os.path.exists(model_path):
            raise HTTPException(status_code=400, detail=f"model {model_path} not exist")

        asr_model = SenseVoiceAx(
            model_path,
            max_len=max_len,
            beam_size=beam_size,
            language=language,
            hot_words=hot_words,
            use_itn=use_itn,
            streaming=streaming,
        )
        asr_model_is_loaded = True
        logger.info("ASR model loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load ASR model: {str(e)}")
        raise

    return JSONResponse(content={"status": "loaded"})

@app.post("/stop_model", summary="Load model")
async def stop_model(
):
    await try_stop_model()

@app.post("/asr", summary="Recognize speech from numpy audio data")
async def recognize_speech(
    audio_data: List[float] = Body(
        ..., embed=True, description="Audio data as list of floats"
    ),
    sample_rate: Optional[int] = Body(16000, description="Audio sample rate in Hz"),
    language: Optional[str] = Body("auto", description="Language"),
):
    """
    接收numpy数组格式的音频数据并返回识别结果

    参数:
    - audio_data: 浮点数列表表示的音频数据
    - sample_rate: 音频采样率(默认16000Hz)

    返回:
    - JSON包含识别文本
    """
    try:
        # 检查模型是否已加载
        if asr_model is None:
            raise HTTPException(status_code=503, detail="ASR model not loaded")

        logger.info(f"Received audio data with length: {len(audio_data)}")

        # 验证并转换数据
        np_audio = validate_audio_data(audio_data)
        if sample_rate != asr_model.sample_rate:
            np_audio = soxr.resample(np_audio, sample_rate, asr_model.sample_rate)

        # 调用模型进行识别
        result = asr_model.infer_waveform(np_audio, language)

        return JSONResponse(content={"text": result})

    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Recognition error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/asr_stream", summary="Recognize speech from numpy audio data")
async def recognize_speech_stream(
    audio_data: List[float] = Body(
        ..., embed=True, description="Audio data as list of floats"
    ),
    sample_rate: Optional[int] = Body(16000, description="Audio sample rate in Hz"),
    language: Optional[str] = Body("auto", description="Language"),
    step: Optional[float] = Body(0.1, description="step in seconds"),
):
    """
    接收numpy数组格式的音频数据并返回识别结果

    参数:
    - audio_data: 浮点数列表表示的音频数据
    - sample_rate: 音频采样率(默认16000Hz)

    返回:
    - JSON包含识别文本
    """
    try:
        # 检查模型是否已加载
        if asr_model is None:
            raise HTTPException(status_code=503, detail="ASR model not loaded")

        logger.info(f"Received audio data with length: {len(audio_data)}")

        # 验证并转换数据
        np_audio = validate_audio_data(audio_data)
        if sample_rate != asr_model.sample_rate:
            np_audio = soxr.resample(np_audio, sample_rate, asr_model.sample_rate)
        # 调用模型进行识别
        def stream_infer(np_audio, step):
            samples = (np_audio * 32768).tolist()

            step = int(step * 16000)
            for i in range(0, len(samples), step):
                is_last = i + step >= len(samples)
                for res in asr_model.stream_infer(samples[i : i + step], is_last, language):
                    yield json.dumps(res) + "\n"
        return StreamingResponse(stream_infer(np_audio, step), media_type="application/json")
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Recognition error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=12347)
