@echo off
setlocal
if not exist venv (python -m venv venv)
call venv\Scripts\activate.bat
pip install -r requirements.txt
if not exist .env (copy .env.example .env)
python manage.py migrate
python manage.py seed_roles
python manage.py check
echo.
echo Setup complete.
echo Create an administrator with: python manage.py createsuperuser
echo Start with: python manage.py runserver
python manage.py runserver
