# FireExtinguisher

자율주행 소방 RC카 프로젝트입니다.
파트별로 폴더를 나눠서 관리합니다.

## 폴더 구성

web 폴더에는 RC카를 관제하는 웹페이지가 들어 있습니다.
Flask와 MariaDB로 만들었고, 설치와 실행 방법은 web/README.md에 정리해 두었습니다.

카메라나 RC카 제어 코드는 camera 같은 폴더를 따로 만들어서 추가할 예정입니다.

## 빠른 실행

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r web\requirements.txt
cd web
python app.py
```
