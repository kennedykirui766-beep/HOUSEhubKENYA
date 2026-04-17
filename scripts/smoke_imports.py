import importlib,sys,traceback
modules=['utils_email_2fa','services.email_service','routes.auth_routes','routes.admin_routes','routes.main','services.notification']
ok=True
for m in modules:
    try:
        importlib.import_module(m)
        print(f'OK: imported {m}')
    except Exception as e:
        ok=False
        print(f'ERROR importing {m}:', type(e).__name__, e)
        traceback.print_exc()
sys.exit(0 if ok else 2)
