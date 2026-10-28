MaixCAM / SG2002 CPU 温度记录器
================================

数据源:
  无线 SSH -> 192.168.1.183:/sys/class/thermal/thermal_zone0/temp

输出:
  /home/jlu/桌面/config/CPU-temperature/cpu_temperature_YYYYMMDD.txt
  每天一个 txt 文件，按 1 Hz 采样。
  每行格式:
    本机时间  temp_c  temp_mc

启动:
  cd /home/jlu/桌面/config
  ./start_cpu_temperature_logger.sh

停止:
  ./stop_cpu_temperature_logger.sh

运行日志:
  /home/jlu/桌面/config/cpu_temperature_logger.out

说明:
  - 复用 voice_keyword_logger.py 的 SSH ControlMaster/keyring 逻辑；
    板子密码从 GNOME Keyring 读取，不在脚本里保存。
  - SSH 断开后自动重连。
  - 采样点来自 SG2002 片上 TEMPSEN，更新周期约 1.048 s。
  - 需要停止时优先用 stop 脚本，避免留下 ssh 子进程。
