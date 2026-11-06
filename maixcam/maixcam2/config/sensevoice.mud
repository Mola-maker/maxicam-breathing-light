[basic]
type = axmodel
model_npu = /root/models/sensevoice-maixcam2/sensevoice.axmodel
model_vnpu =

[extra]
model_type = sensevoice
input_cache = true
output_cache = true
beam_size = 3
language = zh
hot_words = 长,春,昂,长春
use_itn = True
stream_model = /root/models/sensevoice-maixcam2/streaming_sensevoice.axmodel
sensevoice_service_env = /tmp/sensevoice.service.env
server = /root/models/sensevoice-maixcam2/server.py
