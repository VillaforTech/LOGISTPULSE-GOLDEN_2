from fastapi import FastAPI
from pymongo import MongoClient
import os, json, time, threading
import paho.mqtt.client as mqtt

from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Request, Response
import time
REQ=Counter("logistpulse_http_requests_total","HTTP requests",["service","method","path","status"])
LAT=Histogram("logistpulse_http_request_duration_seconds","HTTP latency",["service","path"])

def instrument(app, service):
    @app.middleware("http")
    async def metrics(request: Request, call_next):
        started=time.time(); response=await call_next(request); elapsed=time.time()-started
        path=request.url.path
        REQ.labels(service,request.method,path,str(response.status_code)).inc()
        LAT.labels(service,path).observe(elapsed)
        return response
    @app.get("/metrics", include_in_schema=False)
    def metrics_endpoint():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

app=FastAPI(title="LOGISTPULSE Smart Operations API",version="1.0.0")
instrument(app,"operations-api")
MONGO=os.getenv('MONGO_URI','mongodb://mongo:27017'); MQTT_HOST=os.getenv('MQTT_HOST','mosquitto')
client=MongoClient(MONGO); col=client.operations.telemetry

def on_connect(c,u,f,rc,properties=None): c.subscribe('logistpulse/store/+/device/+/telemetry')
def on_message(c,u,msg):
  try:
    d=json.loads(msg.payload.decode()); d['topic']=msg.topic; d['receivedAt']=time.time(); col.update_one({'deviceId':d['deviceId']},{'$set':d},upsert=True)
  except Exception as e: print('mqtt parse error',e)
def mqtt_loop():
  for _ in range(50):
    try:
      c=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2); c.on_connect=on_connect; c.on_message=on_message; c.connect(MQTT_HOST,1883,60); c.loop_forever(); return
    except Exception as e: print('mqtt waiting',e); time.sleep(2)
threading.Thread(target=mqtt_loop,daemon=True).start()
@app.get('/health')
def health(): return {'status':'UP','service':'operations-api'}
@app.get('/api/operations/{store_id}/devices')
def devices(store_id:str):
  docs=list(col.find({'storeId':store_id},{'_id':0}).sort('deviceId',1))
  for d in docs:
    t=float(d.get('temperatureC',0)); d['state']='CRITICAL' if t>=8 else ('WARNING' if t>=5 else 'OK')
  return docs
