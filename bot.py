import os
import asyncio
import logging
import schedule
import time
from threading import Thread
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
from google.genai import types

# ==============================================================================
# [ 설정 구역 - 사용자 API 키 및 토큰 입력 ]
# 큰따옴표("") 안에 본인의 실제 값만 입력하세요.
# ==============================================================================
TELEGRAM_BOT_TOKEN = "8778354564:AAHxXkMEdoAeEgj3_q3IHJkfJNqQwVsa7jY"
GEMINI_API_KEY = "AQ.Ab8RN6L9VM1-WnnVenYC9CLdiHfzylqxPsKKlGFU6i_nG_YuUw"
MY_TELEGRAM_CHAT_ID = "8986219602"

# 로깅 설정
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Gemini 클라이언트 초기화
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# ==============================================================================
# [ 프롬프트 시스템 디렉티브 ]
# ==============================================================================
SYSTEM_INSTRUCTION = """
[ROLE]
너는 사용자의 개인 한국주식 투자 리서치 AI다.
목표는 단순한 주식 추천 AI가 아니라, 뉴스 → 산업/사업 → 매출 → 비용 → 영업이익 → 순이익 → 수급 → 거래량 → 기술적 흐름 → 시장 기대 → 현재 주가 반영 여부를 연결하여 분석하는 것이다.

가장 중요한 원칙:
1. 사용자가 듣고 싶은 말만 하지 않는다. 무조건 긍정하지 않는다.
2. 긍정적인 근거와 부정적인 근거를 항상 함께 검토한다.
3. 사용자의 의견이 틀렸을 가능성을 반드시 검토한다. (확증 편향 배제)
4. 사실[FACT]과 해석[INTERPRETATION], 불확실성[UNCERTAINTY]을 명확히 구분한다.
5. 확인되지 않은 숫자를 절대 만들어내지 않는다. 데이터가 없으면 "확인 불가" 또는 "데이터 검증 불충분"으로 명시한다.
6. "주가가 오를 이유가 있다"와 "지금 매수해야 한다"를 동일시하지 않는다. 좋은 기업과 좋은 타이밍을 구분한다.
7. 뉴스의 존재보다 실제 실적에 돈으로 연결되는지를 본다. 이미 주가에 선반영된 호재인지 검토한다.
8. 과거 데이터를 현재 데이터처럼 사용하지 않는다.

[COMMON ANALYSIS STRUCTURE]
모든 투자 분석은 가능한 경우 다음 구조를 사용한다:
🟢 긍정적 해석
🔴 부정적 해석
🟡 혼재/복합 영향
📌 핵심 근거
🥊 반론 / 틀릴 가능성
🔮 시나리오
⏱ 단기 영향
📆 중기 영향

응답은 불필요하게 장황하지 않게 Markdown 표와 강조(Bold)를 적절히 활용하여 작성하라.
"""

user_portfolios = {}

def get_naver_finance_news():
    url = "https://finance.naver.com/news/mainnews.naver"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        articles = soup.select('.mainNewsList .articleSubject a')
        news_list = []
        for a in articles[:10]:
            title = a.get_text().strip()
            link = "https://finance.naver.com" + a['href']
            news_list.append(f"- {title} ({link})")
        return "\n".join(news_list) if news_list else "뉴스 수집 실패"
    except Exception as e:
        return f"뉴스 수집 중 오류 발생: {e}"

def call_gemini(prompt: str) -> str:
    try:
        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.3
            )
        )
        return response.text
    except Exception as e:
        return f"⚠️ 분석 모델 호출 중 오류가 발생했습니다: {e}"

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_msg = (
        "📈 **한국주식 투자 리서치 AI 봇에 오신 것을 환영합니다.**\n\n"
        "객관적 데이터, 수급, 실적 연결성 및 반론 분석을 바탕으로 엄격한 리서치를 제공합니다.\n"
        "사용 가능한 명령어 목록을 보시려면 `!명령어` 를 입력하세요."
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.effective_user.id

    if not text.startswith("!"):
        response = call_gemini(f"사용자 질의: {text}\n위 질의에 대해 투자 시스템 원칙에 따라 분석 답변을 작성하세요.")
        await update.message.reply_text(response, parse_mode="Markdown")
        return

    parts = text.split(maxsplit=2)
    cmd = parts[0]
    arg1 = parts[1] if len(parts) > 1 else ""
    arg2 = parts[2] if len(parts) > 2 else ""

    if cmd == "!명령어":
        help_text = (
            "📌 **사용 가능한 명령어 목록**\n\n"
            "• `!뉴스분석 [링크]` - 뉴스 수혜/피해 및 실적 연결성 분석\n"
            "• `!뉴스기간 [종목] [기간]` - 예: `!뉴스기간 삼성전자 6개월`\n"
            "• `!실적발표 [종목]` - 실적 컨센서스 대비 및 주가 괴리 분석\n"
            "• `!거시분석 [종목]` - 환율/금리/원자재 등 거시지표 영향 분석\n"
            "• `!이벤트 [종목]` - 주요 이벤트 및 선반영 여부 분석\n"
            "• `!뉴스실적 [종목]` - 최근 3개월 뉴스의 실제 실적 반영 분석\n"
            "• `!투자검사 [종목]` - 현재가 매수 적합성, 손절가/익절가 제시\n"
            "• `!보유종목 [종목]` - 보유종목 등록/조회\n"
            "• `!본전 [종목]` - 매수가 기준 추가매수 및 평단가 수급 분석\n"
            "• `!투자일기` - 고쳐야 할 투자 습관 TOP 3 분석\n"
            "• `!투자복기` - 투자 결과 및 실수/잘한 점 복기\n"
            "• `!추세 [종목] [기간]` - 주봉 기준 추세 분석\n"
            "• `!손절가 [종목]` - 보수적/중립/공격적 손절가 제시\n"
            "• `!트렌드 [종목]` - 단기 테마 vs 추세 전환 신호 구분\n"
            "• `!비교 [종목]` - 경쟁사 간 객관적 펀더멘털 비교\n"
            "• `!저평가` - 실적 성장 및 PER/PBR 기준 후보 탐색\n"
            "• `!서프라이즈` - 최근 실적 서프라이즈 정리\n"
            "• `!목표주가변경` - 증권사 목표주가 변경 추이\n"
            "• `!포트폴리오` - 전체 포트폴리오 위험/진단\n"
            "• `!분류기준` - 투자자 유형별 분류 기준 설명"
        )
        await update.message.reply_text(help_text, parse_mode="Markdown")

    elif cmd == "!보유종목":
        if not arg1:
            user_list = user_portfolios.get(user_id, [])
            if not user_list:
                await update.message.reply_text("현재 등록된 보유종목이 없습니다. `!보유종목 [종목명]`으로 추가하세요.")
            else:
                stocks = ", ".join(user_list)
                prompt = f"사용자의 현재 보유종목 목록: [{stocks}]. 종합 수급, 뉴스, 매수 적합성 및 리스크를 요약 분석하라."
                res = call_gemini(prompt)
                await update.message.reply_text(f"📋 **현재 보유종목**: {stocks}\n\n{res}", parse_mode="Markdown")
        else:
            user_list = user_portfolios.setdefault(user_id, [])
            if arg1 not in user_list:
                user_list.append(arg1)
                await update.message.reply_text(f"✅ [{arg1}] 종목이 보유 목록에 등록되었습니다.")
            else:
                await update.message.reply_text(f"이미 등록된 종목입니다: [{arg1}]")

    elif cmd == "!분류기준":
        prompt = "!분류기준 명령어가 입력되었습니다. 🚀 성장형, 💰 배당형, ⚡ 단기 매매자 분류 기준 및 특징을 설명하세요."
        res = call_gemini(prompt)
        await update.message.reply_text(res, parse_mode="Markdown")

    elif cmd in [
        "!뉴스분석", "!뉴스기간", "!실적발표", "!거시분석", "!이벤트", 
        "!뉴스실적", "!투자검사", "!본전", "!투자일기", "!투자복기", 
        "!추세", "!손절가", "!트렌드", "!비교", "!저평가", 
        "!서프라이즈", "!목표주가변경", "!포트폴리오"
    ]:
        if cmd in ["!뉴스분석", "!실적발표", "!거시분석", "!이벤트", "!뉴스실적", "!투자검사", "!본전", "!추세", "!손절가", "!트렌드", "!비교"] and not arg1:
            await update.message.reply_text(f"⚠️ 종목명 또는 대상 정보가 누락되었습니다.\n사용예: `{cmd} 삼성전자`", parse_mode="Markdown")
            return
        
        prompt = f"명령어: {text}\n대상: {arg1} {arg2}\n위 시스템 가이드라인에 맞춰 strict하게 리서치 보고서를 작성하라."
        res = call_gemini(prompt)
        await update.message.reply_text(res, parse_mode="Markdown")

    else:
        await update.message.reply_text("알 수 없는 명령어입니다. `!명령어`를 통해 입력 가능한 명령어를 확인하세요.")

async def send_scheduled_message(bot, chat_id: str, text: str):
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"정기 메시지 전송 실패: {e}")

def run_07am_job(bot, loop):
    news_data = get_naver_finance_news()
    prompt = f"[07시 알림]\n주요 뉴스:\n{news_data}\n1. 핵심 경제 뉴스 10개 정리(제목/핵심/영향/수혜·피해기업).\n2. 개장 전 집중 확인 국내 상장사 3개 정리."
    res = call_gemini(prompt)
    msg = f"🌅 **[07:00 AM 주요 경제 뉴스 리서치]**\n\n{res}"
    asyncio.run_coroutine_threadsafe(send_scheduled_message(bot, MY_TELEGRAM_CHAT_ID, msg), loop)

def run_12pm_job(bot, loop):
    current_time = time.strftime("%Y-%m-%d %H:%M KST")
    prompt = f"[12시 투자 알림]\n기준일시: {current_time}\n규칙: 12시 투자 알림 항목 ①~⑮ 작성. 당일 +20% 급등주 불확실 시 '검증 불충분' 명시."
    res = call_gemini(prompt)
    msg = f"☀️ **[12:00 PM 장중 투자 분석 알림]**\n\n{res}"
    asyncio.run_coroutine_threadsafe(send_scheduled_message(bot, MY_TELEGRAM_CHAT_ID, msg), loop)

def run_saturday_job(bot, loop):
    prompt = "[주간 토요일 알림] 주간 하락/상승 TOP10, 수급 및 주간 테마 분류 리포트 작성."
    res = call_gemini(prompt)
    msg = f"📅 **[주간 토요일 종합 분석 보고서]**\n\n{res}"
    asyncio.run_coroutine_threadsafe(send_scheduled_message(bot, MY_TELEGRAM_CHAT_ID, msg), loop)

def run_monthly_job(bot, loop):
    prompt = "[월간 1일 알림] 최근 분기 실적 서프라이즈 종목 3개 및 보유종목 월간 점검 보고서 작성."
    res = call_gemini(prompt)
    msg = f"🗓 **[월간 1일 포트폴리오 및 서프라이즈 점검]**\n\n{res}"
    asyncio.run_coroutine_threadsafe(send_scheduled_message(bot, MY_TELEGRAM_CHAT_ID, msg), loop)

def schedule_checker(bot, loop):
    schedule.every().day.at("07:00").do(run_07am_job, bot, loop)
    schedule.every().day.at("12:00").do(run_12pm_job, bot, loop)
    schedule.every().saturday.at("09:00").do(run_saturday_job, bot, loop)
    
    def monthly_check():
        if time.strftime("%d") == "01":
            run_monthly_job(bot, loop)
            
    schedule.every().day.at("08:00").do(monthly_check)

    while True:
        schedule.run_pending()
        time.sleep(30)

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    # 파이썬 3.14 최신 버전 완전 대응 이벤트 루프 구동
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    t = Thread(target=schedule_checker, args=(app.bot, loop), daemon=True)
    t.start()

    print("🚀 주식 리서치 AI 텔레그램 봇이 정상 실행되었습니다!")
    app.run_polling()

if __name__ == "__main__":
    main()