from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os, psycopg, time, json, uuid
from kafka import KafkaProducer

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

app=FastAPI(title="LOGISTPULSE Fulfillment API",version="1.0.0")
instrument(app,"fulfillment-api")
DB=os.getenv('FULFILLMENT_DB_URL','postgresql://logist:logist_demo@postgres:5432/fulfillment_db'); KAFKA=os.getenv('KAFKA_BOOTSTRAP','redpanda:9092')
def conn(): return psycopg.connect(DB)
def bootstrap():
  for _ in range(50):
    try:
      with conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS orders(order_id text primary key, store_id text, channel text, total numeric, status text, created_at numeric, updated_at numeric)"); c.commit(); return
    except Exception: time.sleep(1)
bootstrap()
def producer():
  for _ in range(20):
    try:return KafkaProducer(bootstrap_servers=KAFKA,value_serializer=lambda v:json.dumps(v).encode())
    except Exception:time.sleep(1)
  return None
class NewOrder(BaseModel): storeId:str='STORE-042'; channel:str='MOBILE'; total:float=18.50
@app.get('/health')
def health(): return {'status':'UP','service':'fulfillment-api'}
@app.get('/api/fulfillment/orders')
def orders():
  with conn() as c: rows=c.execute("SELECT order_id,store_id,channel,total,status,created_at,updated_at FROM orders ORDER BY created_at DESC LIMIT 20").fetchall()
  return [{'orderId':r[0],'storeId':r[1],'channel':r[2],'total':float(r[3]),'status':r[4],'createdAt':r[5],'updatedAt':r[6]} for r in rows]
@app.post('/api/fulfillment/orders',status_code=201)
def create(o:NewOrder):
  oid='ORD-'+uuid.uuid4().hex[:6].upper(); now=time.time()
  with conn() as c: c.execute("INSERT INTO orders VALUES (%s,%s,%s,%s,'WAITING',%s,%s)",(oid,o.storeId,o.channel,o.total,now,now)); c.commit()
  p=producer();
  if p: p.send('logistpulse.orders',{'orderId':oid,'event':'ORDER_CREATED','storeId':o.storeId}); p.flush(); p.close()
  return {'orderId':oid,'status':'WAITING'}
