"""
Модуль для работы с GigaChat API
"""

from gigachat import GigaChat

AUTHORIZATION_KEY = "MDE5ZTUwOGEtZWE2My03MTQ0LWJmMTMtNDU3YjRjNDU3NmE3OjZjMGEwMmNjLWMwYWEtNGRlYy1iNGNmLTUyOGY1ZGM4MWYzZg=="

def get_gigachat_response(user_message, tasks_context):
    """Отправляет запрос к GigaChat и возвращает ответ"""
    try:
        print(f"[GigaChat] Запрос: {user_message[:50]}...")
        
        # Подключаемся к GigaChat
        giga = GigaChat(
            credentials=AUTHORIZATION_KEY,
            verify_ssl_certs=False,
            scope="GIGACHAT_API_PERS",
            timeout=30
        )
        
        # Формируем запрос
        full_prompt = f"""Ты — поддерживающий ассистент по продуктивности. Отвечай мягко, коротко.

Текущие дела пользователя:
{chr(10).join(tasks_context) if tasks_context else 'Нет активных дел'}

Вопрос пользователя: {user_message}

Ответ:"""
        
        # Отправляем запрос
        response = giga.chat(full_prompt)
        result = response.choices[0].message.content
        giga.close()
        
        print(f"[GigaChat] Ответ получен: {result[:50]}...")
        return result
        
    except Exception as e:
        print(f"[GigaChat] Ошибка: {e}")
        return f"Ошибка: {str(e)}"