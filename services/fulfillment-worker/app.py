import os,time,psycopg,json
from kafka import KafkaConsumer
DB=os.getenv('FULFILLMENT_DB_URL','postgresql://logist:logist_demo@postgres:5432/fulfillment_db'); KAFKA=os.getenv('KAFKA_BOOTSTRAP','redpanda:9092')
def conn(): return psycopg.connect(DB)
while True:
  try:
    consumer=KafkaConsumer('logistpulse.orders',bootstrap_servers=KAFKA,group_id='kitchen-worker',auto_offset_reset='earliest',value_deserializer=lambda b:json.loads(b.decode()))
    break
  except Exception as e: print('kafka waiting',e); time.sleep(2)
for msg in consumer:
  oid=msg.value.get('orderId');
  try:
    with conn() as c:
      c.execute("UPDATE orders SET status='PREPARING',updated_at=%s WHERE order_id=%s",(time.time(),oid)); c.commit()
    time.sleep(4)
    with conn() as c:
      c.execute("UPDATE orders SET status='READY',updated_at=%s WHERE order_id=%s",(time.time(),oid)); c.commit()
  except Exception as e: print('worker error',e)
