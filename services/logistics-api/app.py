from fastapi import FastAPI
import os, psycopg, time, random

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

app=FastAPI(title="LOGISTPULSE Distribution API",version="1.0.0")
instrument(app,"logistics-api")
DB=os.getenv("LOGISTICS_DB_URL","postgresql://logist:logist_demo@postgres:5432/logistics_db")
def conn(): return psycopg.connect(DB)
def bootstrap():
  for _ in range(40):
    try:
      with conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS trucks(truck_id text primary key, route text, status text, stops_done int, stops_total int, eta_min int, temp_c numeric, lat numeric, lon numeric)")
        if c.execute("SELECT count(*) FROM trucks").fetchone()[0]==0:
          c.executemany("INSERT INTO trucks VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",[
            ('TRUCK-017','Quito Norte','IN_TRANSIT',6,11,28,3.8,-0.1807,-78.4678),('TRUCK-023','Quito Sur','LOADING',0,8,64,4.2,-0.245,-78.53)])
        c.commit(); return
    except Exception: time.sleep(1)
bootstrap()
@app.get('/health')
def health(): return {'status':'UP','service':'logistics-api'}
@app.get('/api/distribution/trucks')
def trucks():
  with conn() as c: rows=c.execute("SELECT * FROM trucks ORDER BY truck_id").fetchall()
  return [{'truckId':r[0],'route':r[1],'status':r[2],'stopsDone':r[3],'stopsTotal':r[4],'etaMin':r[5],'temperatureC':float(r[6]),'lat':float(r[7]),'lon':float(r[8]),'coldChain':'OK' if r[6]<=5 else 'ALERT'} for r in rows]
@app.post('/api/distribution/trucks/{truck_id}/advance')
def advance(truck_id:str):
  with conn() as c:
    r=c.execute("UPDATE trucks SET stops_done=LEAST(stops_total,stops_done+1), eta_min=GREATEST(0,eta_min-6), temp_c=temp_c+(random()-.5)/2 WHERE truck_id=%s RETURNING stops_done,eta_min,temp_c",(truck_id,)).fetchone(); c.commit()
  return {'truckId':truck_id,'stopsDone':r[0],'etaMin':r[1],'temperatureC':float(r[2])}
