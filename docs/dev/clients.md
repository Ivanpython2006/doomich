# Клиенты Android, Windows и Linux

Клиенты написаны на Flutter и собраны в одно рабочее пространство pub (`apps/client/pubspec.yaml`):
общий код вынесен в пакеты, а приложения под платформы — тонкие оболочки со своей навигацией.

| Каталог | Что внутри |
|---|---|
| `packages/doomich_core` | Чистый Dart: HTTP-клиент с обновлением сессии, SSE-разбор потоковых ответов, модели API, репозитории, голосовой протокол WebSocket, офлайн-кэш расписания. Тестируется без Flutter (`dart test`) |
| `packages/doomich_ui` | Экраны и состояние (Riverpod 3): онбординг по приглашению, чат (с источниками, инкогнито, голосом), расписание, документы, конспекты, настройки; темы, локализация RU/EN, звук |
| `mobile` | Android: нижняя навигация, кнопка «нажми и говори», сканер QR (код приглашения и вход на компьютере) |
| `desktop` | Windows и Linux: две панели (чаты и разговор), горячие клавиши (Ctrl+N, удерживать Ctrl+Пробел для голоса), вход по QR с телефона |

## Сборка

```bash
cd apps/client && flutter pub get
cd mobile  && flutter build apk --release --dart-define=DOOMICH_API=https://doomich.example.ru
cd desktop && flutter build linux --release --dart-define=DOOMICH_API=https://doomich.example.ru
cd desktop && flutter build windows --release --dart-define=DOOMICH_API=https://doomich.example.ru   # на Windows
```

Для Android нужны Android SDK и **JDK 21**: Android Gradle Plugin 9.3 на JDK 17 падает на проверке lint
(`NoSuchMethodError: List.removeLast`). NDK нужной версии Gradle скачает сам.

`DOOMICH_API` — адрес сервера по умолчанию; пользователь может сменить его в приложении («Адрес сервера»
на экране приветствия или в настройках), поэтому одна сборка подходит для нескольких установок.

CI собирает APK, архив для Linux и каталог для Windows на каждый коммит (артефакты задания).

### Подпись Android

Положите `apps/client/mobile/android/key.properties` (в git не попадает):

```properties
storeFile=/путь/к/doomich-release.jks
storePassword=...
keyAlias=doomich
keyPassword=...
```

Без файла релиз подписывается отладочным ключом — годится для проверки, не для распространения.
Идентификатор приложения — `ru.doomich.app`.

### Linux

Для сборки: `clang cmake ninja-build pkg-config libgtk-3-dev libsecret-1-dev libgstreamer1.0-dev
libgstreamer-plugins-base1.0-dev`.

У пользователя должны быть `libgtk-3-0`, `libsecret-1-0`, `libgstreamer1.0-0`,
`libgstreamer-plugins-base1.0-0`. Дополнительно:

- **токены** хранятся в системном хранилище паролей (GNOME Keyring, KWallet); если его нет
  (минимальные окружения), — в файле с правами 0600 в каталоге данных приложения;
- **озвучка** работает через GStreamer, если установлены `gstreamer1.0-plugins-good`; иначе приложение само
  выбирает `pw-play`, `paplay`, `ffplay` или `aplay`. Плагин audioplayers без GStreamer аварийно завершал
  бы приложение при открытии чата, поэтому выбор делается до создания проигрывателя;
- **микрофон** — через `parecord` (PulseAudio или PipeWire).

## Как клиент работает с сервером

- Вход: код приглашения → псевдоним и пароль → пара токенов (доступ 15 минут, обновление 30 дней,
  с ротацией). Токены — в защищённом хранилище ОС. При 401 клиент один раз обновляет сессию
  (параллельные запросы ждут то же обновление) и повторяет запрос.
- Ответы чата приходят потоком (SSE): статусы инструментов («смотрю расписание»), текст, источники `[n]`.
- Голос: запись PCM 16 кГц → WebSocket `/v1/voice` → расшифровка, ответ и озвучка по предложениям.
- Расписание показывается по часам вуза (сервер отдаёт время со смещением пояса вуза), на любом
  устройстве; последняя загруженная неделя доступна без сети.
- Инкогнито-чат хранится только на устройстве: история передаётся с каждым вопросом.

## Тесты

```bash
cd apps/client/packages/doomich_core && dart test     # API-клиент, SSE, голосовой протокол, разбор времени
cd apps/client/packages/doomich_ui && flutter test    # онбординг, чат, настройки, очередь озвучки
cd apps/client/mobile && flutter test
cd apps/client/desktop && flutter test
```

Сквозной тест против сервера — см. [локальную разработку](local.md#тесты-и-проверки).
