import importlib.util
import sys

paths = ['../config.py', 'services/provider_service.py']

for rel in paths:
    path = __file__.rsplit('/', 1)[0] + '/' + rel if '/' in __file__ else __file__.rsplit('\\', 1)[0] + '\\' + rel
    try:
        spec = importlib.util.spec_from_file_location('mod', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        print(path + ' import OK')
    except Exception as e:
        print(path + ' ERROR: ' + str(e))
        sys.exit(1)

print('All imports OK')
