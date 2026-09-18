# Красивый Discord-бот

## Профиль с GIF / баннером

`/profile` — красивая карточка профиля

Кастомизация:
- `/setbanner <ссылка>` — GIF или картинка (Imgur, Tenor, Discord CDN, прямые .gif/.png)
- `/setbanner none` — убрать баннер
- `/setbio <текст>` — описание под ником
- `/setcolor #FF55AA` — цвет полоски эмбеда

## Экономика (кнопки в профиле)
Daily • Work • Crime • Банк • Магазин

## Остальное
`/pay` `/rob` `/top` `/gamble` `/inventory`  
`/mute` `/unmute` `/report`  
Верификация + автомод

## Установка
1. Токен в `config.py`
2. Intents: Members + Message Content  
3. `pip install -r requirements.txt`
4. `python main.py`
5. `/setup` + роль бота **выше** всех выдаваемых ролей
