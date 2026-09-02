import os,time,json,random
import paho.mqtt.client as mqtt
HOST=os.getenv('MQTT_HOST','mosquitto')
devices=[('FRYER-01',175),('FRYER-02',178),('FREEZER-01',3.5),('FREEZER-02',8.7),('POS-01',0)]
while True:
  try:
    c=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2); c.connect(HOST,1883,60); break
  except Exception: time.sleep(2)
while True:
  for device,base in devices:
    temp=base+random.uniform(-.6,.6) if base else 0
    payload={'storeId':'STORE-042','deviceId':device,'temperatureC':round(temp,1),'online':True,'ts':time.time()}
    c.publish(f'logistpulse/store/STORE-042/device/{device}/telemetry',json.dumps(payload),qos=0)
  c.loop(timeout=.1); time.sleep(3)
