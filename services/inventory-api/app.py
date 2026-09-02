from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os, psycopg, time

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

app=FastAPI(title="LOGISTPULSE Inventory API",version="1.0.0")
instrument(app,"inventory-api")
DB=os.getenv("INVENTORY_DB_URL","postgresql://logist:logist_demo@postgres:5432/inventory_db")

def conn(): return psycopg.connect(DB)

def bootstrap():
    for _ in range(40):
        try:
            with conn() as c:
                c.execute("CREATE TABLE IF NOT EXISTS inventory(store_id text, sku text, item_name text, unit text, stock numeric, forecast_4h numeric, PRIMARY KEY(store_id,sku))")
                n=c.execute("SELECT count(*) FROM inventory").fetchone()[0]
                if n==0:
                    c.executemany("INSERT INTO inventory VALUES (%s,%s,%s,%s,%s,%s)",[
                      ('STORE-042','CHK','Pollo','kg',38,61),('STORE-042','POT','Papas','kg',74,52),('STORE-042','OIL','Aceite','L',21,30),('STORE-042','PKG','Empaques','u',425,310)])
                c.commit(); return
        except Exception: time.sleep(1)
bootstrap()

class Adjustment(BaseModel): delta: float
@app.get('/health')
def health(): return {'status':'UP','service':'inventory-api'}
@app.get('/api/inventory/{store_id}')
def inventory(store_id:str):
    with conn() as c:
        rows=c.execute("SELECT sku,item_name,unit,stock,forecast_4h FROM inventory WHERE store_id=%s ORDER BY item_name",(store_id,)).fetchall()
    return [{'sku':r[0],'item':r[1],'unit':r[2],'stock':float(r[3]),'forecast4h':float(r[4]),'risk':'HIGH' if r[3]<r[4]*.75 else ('MEDIUM' if r[3]<r[4] else 'LOW')} for r in rows]
@app.post('/api/inventory/{store_id}/{sku}/adjust')
def adjust(store_id:str,sku:str,a:Adjustment):
    with conn() as c:
        r=c.execute("UPDATE inventory SET stock=stock+%s WHERE store_id=%s AND sku=%s RETURNING stock",(a.delta,store_id,sku)).fetchone(); c.commit()
    if not r: raise HTTPException(404,'SKU not found')
    return {'storeId':store_id,'sku':sku,'stock':float(r[0])}
