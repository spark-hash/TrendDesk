if __name__ == '__main__':
    from getpass import getpass
    from pathlib import Path
    from app.advisor import Advisor, AIConfig
    from app.store import Store
    
    store = Store(Path("data/trenddesk.db"))
    service = Advisor(store)
    if service.status()["key_storage"] != "dpapi":
        secret = getpass("请重新输入 OpenAI API Key（隐藏输入，按回车保存；留空取消）：").strip()
        if not secret:
            raise SystemExit(2)
        try:
            service.configure(AIConfig(**service.profiles["routine"], key=secret))
        except Exception:
            raise SystemExit("保存失败，原服务继续运行。")
        if Advisor(store).key != secret:
            raise SystemExit("未能验证加密存储，原服务继续运行。")
