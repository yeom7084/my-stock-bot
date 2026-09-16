import os
import time
import asyncio
import logging
import schedule
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

import requests
from bs4 import BeautifulSoup

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

from google import genai

# ==============================================================================
# [ 1. 설정 구역 - API 키 및 토큰 ]
# ==============================================================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8778354564:AAHxXkMEdoAeEgj3_q3IHJkfJNqQwVsa7jY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AQ.Ab8RN6L9VM1-WnnVenYC9CLdiHfzylqxPsKK1GFU6i_nG_YuUw")
MY_TELEGRAM_CHAT_ID = os.environ.get("MY_TELEGRAM_CHAT_ID", "8986219602")

# 로깅 설정
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Gemini 클라이언트 초기화
client = genai.Client(api_key=GEMINI_API_KEY)

# 메인 이벤트 루프 참조용
main_loop = None

# ==============================================================================
# [ 2. Render 포트 타임아웃 방지용 Dummy HTTP Server ]
# ==============================================================================
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running successfully!")

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    server.serve_forever()

# ==============================================================================
# [ 3. Gemini API 호출 함수 (503 과부하 자동 재시도 포함) ]
# ==============================================================================
def ask_gemini_with_retry(prompt: str, max_retries: int = 3) -> str:
    """
    503 과부하 발생 시 최대 max_retries회까지 2초 간격으로 자동 재시도합니다.
    """
    model_name = "gemini-3.6-flash"
    
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            return response.text
        except Exception as e:
            # 503 에러 또는 서버 과부하 발생 시 재시도
            if ("503" in str(e) or "UNAVAILABLE" in str(e)) and attempt < max_retries - 1:
                logging.warning(f"⚠️ Gemini API 503 과부하 발생 ({attempt + 1}/{max_retries}). 2초 후 재시도합니다...")
                time.sleep(2)
                continue
            raise e

# ==============================================================================
# [ 4. 자동 알림 스케줄러 로직 ]
# ==============================================================================
async def send_scheduled_briefing(app):
    """지정된 시간에 실행될 자동 브리핑/알림 로직"""
    try:
        logging.info("⏰ 자동 스케줄 알림 발송 중...")
        prompt = "오늘 주요 주식 시장 이슈와 뉴스 핵심을 간결하게 요약해서 브리핑해줘."
        briefing = ask_gemini_with_retry(prompt)
        # 마크다운 파싱 에러 방지를 위해 plain text로 전송
        await app.bot.send_message(chat_id=MY_TELEGRAM_CHAT_ID, text=f"📢 [자동 브리핑]\n\n{briefing}")
    except Exception as e:
        logging.error(f"❌ 자동 알림 발송 실패: {e}")

def schedule_job_bridge(app):
    """schedule 라이브러리 작업을 asyncio 이벤트 루프로 안전하게 전달"""
    if main_loop and main_loop.is_running():
        asyncio.run_coroutine_threadsafe(send_scheduled_briefing(app), main_loop)

def run_scheduler(app):
    """백그라운드에서 주기적으로 스케줄 체크하는 루프"""
    schedule.every().day.at("08:30").do(schedule_job_bridge, app=app)
    schedule.every().day.at("18:00").do(schedule_job_bridge, app=app)
    
    logging.info("📅 백그라운드 스케줄러가 정상 작동 중입니다.")
    while True:
        schedule.run_pending()
        time.sleep(30)

# ==============================================================================
# [ 5. 텔레그램 핸들러 (BadRequest/마크다운 오류 완벽 방지) ]
# ==============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("안녕하세요! 주식 리서치 AI 봇입니다. 질문이나 명령어를 입력해주세요.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    try:
        # 1. Gemini API 연동 (503 재시도)
        reply = ask_gemini_with_retry(user_text)
        
        # 2. 마크다운 특수문자 에러(Can't parse entities)를 방지하기 위해 
        # parse_mode 없이 일반 텍스트 형태로 안전하게 답변 전송
        await update.message.reply_text(reply)
        
    except Exception as e:
        logging.error(f"메시지 처리 오류: {e}")
        await update.message.reply_text(f"⚠️ 분석 모델 호출 중 오류가 발생했습니다:\n{e}")

# ==============================================================================
# [ 6. 메인 실행부 ]
# ==============================================================================
def main():
    global main_loop
    
    # 1. Render 웹서비스 포트 유지용 가짜 서버 백그라운드 실행
    Thread(target=run_dummy_server, daemon=True).start()

    # 2. 텔레그램 봇 어플리케이션 생성
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # 3. 텔레그램 메시지 핸들러 등록
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # 4. 백그라운드 자동 알림 스케줄러 실행
    Thread(target=run_scheduler, args=(app,), daemon=True).start()

    logging.info("🚀 주식 리서치 AI 텔레그램 봇이 활성화되었습니다!")
    
    # 5. 메인 asyncio 루프 저장 및 Polling 시작
    main_loop = asyncio.get_event_loop()
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

