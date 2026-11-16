# Думыч для Android

Клиент «Думыча» для Android. Общий код живёт в пакетах рабочего пространства:
`../packages/doomich_core` (API, модели, SSE, голосовой протокол) и
`../packages/doomich_ui` (экраны, состояние, локализация RU/EN).

Особенности мобильной версии: вход по коду приглашения или QR, кнопка «нажми и говори»,
подтверждение входа на компьютере сканированием QR (Настройки → «Войти на компьютере»).

## Запуск и сборка

```bash
flutter run --dart-define=DOOMICH_API=http://10.0.2.2:8000   # эмулятор → сервер на этом ПК
flutter build apk --release --dart-define=DOOMICH_API=https://doomich.example.ru
```

Адрес сервера можно сменить и в самом приложении: «Адрес сервера» на экране приветствия или в настройках.

Подпись релиза: положите `android/key.properties` (`storeFile`, `storePassword`, `keyAlias`, `keyPassword`)
рядом с keystore — файл в git не попадает. Без него релиз подписывается отладочным ключом.

Тесты: `flutter test`. Подробности — в `docs/dev/clients.md`.
