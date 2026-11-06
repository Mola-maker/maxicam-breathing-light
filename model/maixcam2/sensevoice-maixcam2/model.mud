[basic]
type = axmodel
model_npu = sensevoice.axmodel
model_vnpu =

[extra]
model_type = sensevoice
input_cache = true
output_cache = true
beam_size = 3
language = auto
hot_words = None,
use_itn = True
stream_model = streaming_sensevoice.axmodel
sensevoice_service_env = /tmp/sensevoice.service.env
server = server.py