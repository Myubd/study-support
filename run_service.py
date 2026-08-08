"""
run_service.py
----------------
study-support backend の、gateway統合exe向けの最小ランチャー。

archlife-fastapi/launch_fastapi.py と同じ契約(PORT/DATA_DIRを環境変数で
受け取り、uvicornを起動するだけ)にしている。Ollamaの管理・ブラウザ起動は
gateway自身(launch_gateway.py)が1回だけ行うため、ここでは行わない
(interview_appの単体exe版launch_fastapi.pyとは役割が異なる)。

launch_gateway.py側との約束事:
  - 環境変数 PORT: 待ち受けポート(既定 8100)
  - 環境変数 DATA_DIR: study.db の保存先ディレクトリ
  - 環境変数 GATEWAY_AUTH_TOKEN: service_auth.py が検証する共有シークレット
    (main.py側の起動時チェックで必須。無ければ起動時に例外で落ちる)
"""
from __future__ import annotations

import multiprocessing
import os

from local_ai_core import launcher_kit as lk

if __name__ == "__main__":
    multiprocessing.freeze_support()


def main() -> None:
    lk.hide_console_window()
    lk.fix_stdio()
    lk.suppress_child_console()

    port = int(os.environ.get("PORT", "8100"))
    data_dir = os.environ.get("DATA_DIR") or os.path.join(os.path.expanduser("~"), ".lifesupportos")
    os.makedirs(data_dir, exist_ok=True)

    # main.py が読む環境変数を、launch_gateway.pyが渡すDATA_DIRから組み立てる
    os.environ.setdefault("STUDY_DB_PATH", os.path.join(data_dir, "study.db"))

    lk.kill_existing_process(port)

    print(f"[study_support] starting on 127.0.0.1:{port}", flush=True)
    print(f"[study_support] db path: {os.environ['STUDY_DB_PATH']}", flush=True)

    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=port, log_level="warning", loop="asyncio")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            lk.fix_stdio()
        except Exception:
            pass
        lk.write_crash_log("LifeSupportOS", "study_support run_service.py の main()内で例外が発生しました", e)
        raise
