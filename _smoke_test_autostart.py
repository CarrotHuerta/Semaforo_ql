import time
import mlflow_integration as mi

saved = {}
def cb(uri):
    saved['uri'] = uri

start = time.time()
result = mi.start_local_server_if_needed({}, save_config_callback=cb)
print('result=', result, 'elapsed=', round(time.time() - start, 1))
print('saved=', saved)
print('reachable now:', mi._is_reachable(mi.DEFAULT_LOCAL_URI))
mi.stop_local_server()
time.sleep(2)
print('reachable after stop:', mi._is_reachable(mi.DEFAULT_LOCAL_URI))
