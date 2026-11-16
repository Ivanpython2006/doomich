# Думыч для Windows и Linux

Клиент «Думыча» для компьютеров: две панели (список чатов и разговор), горячие клавиши
(Ctrl+N — новый чат, удерживать Ctrl+Пробел — голосовой вопрос), вход по QR с телефона.
Общий код — в `../packages/doomich_core` и `../packages/doomich_ui`.

## Запуск и сборка

```bash
flutter run -d linux --dart-define=DOOMICH_API=http://localhost:8000
flutter build linux --release --dart-define=DOOMICH_API=https://doomich.example.ru
flutter build windows --release --dart-define=DOOMICH_API=https://doomich.example.ru
```

Сборка под Linux требует `clang cmake ninja-build pkg-config libgtk-3-dev libsecret-1-dev
libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev`.

Что нужно на компьютере пользователя (Linux):

- `libgtk-3-0`, `libsecret-1-0`, `libgstreamer1.0-0`, `libgstreamer-plugins-base1.0-0` — без них приложение не запустится;
- хранилище паролей (GNOME Keyring или KWallet) — иначе токены хранятся в файле с правами 0600;
- для озвучки — `gstreamer1.0-plugins-good` или любая из утилит `pw-play`, `paplay`, `ffplay`, `aplay`;
- для микрофона — `parecord` (PulseAudio или PipeWire).

Тесты: `flutter test`. Подробности — в `docs/dev/clients.md`.
