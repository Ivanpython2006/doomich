import 'dart:math';

/// Генератор псевдонимов на устройстве (сервер тоже умеет — /v1/auth/pseudonyms).
class Pseudonyms {
  static const _adjRu = ['Тихий', 'Быстрый', 'Мудрый', 'Смелый', 'Ясный', 'Добрый', 'Звёздный', 'Северный', 'Весёлый', 'Ловкий'];
  static const _nounRu = ['Енот', 'Филин', 'Лис', 'Кит', 'Ёж', 'Барсук', 'Сокол', 'Бобёр', 'Пингвин', 'Дельфин'];
  static const _adjEn = ['Quiet', 'Swift', 'Wise', 'Brave', 'Clever', 'Bright', 'Calm', 'Lucky'];
  static const _nounEn = ['Raccoon', 'Owl', 'Fox', 'Whale', 'Hedgehog', 'Falcon', 'Beaver', 'Otter'];

  static List<String> suggest(String locale, {int count = 5, Random? random}) {
    final rnd = random ?? Random.secure();
    final ru = !locale.startsWith('en');
    final adj = ru ? _adjRu : _adjEn;
    final noun = ru ? _nounRu : _nounEn;
    return List.generate(count, (_) => '${adj[rnd.nextInt(adj.length)]}${noun[rnd.nextInt(noun.length)]}${10 + rnd.nextInt(90)}');
  }
}

const _firstNames = {
  'александр', 'алексей', 'андрей', 'анна', 'анастасия', 'артём', 'артем', 'дарья', 'дмитрий', 'екатерина',
  'елена', 'иван', 'игорь', 'ирина', 'кирилл', 'максим', 'мария', 'михаил', 'никита', 'ольга', 'павел',
  'полина', 'сергей', 'софия', 'татьяна', 'юлия', 'alexander', 'ivan', 'maria', 'anna', 'dmitry', 'sergey',
};
const _surnameSuffixes = ['ов', 'ев', 'ёв', 'ин', 'ова', 'ева', 'ина', 'ский', 'ская', 'енко'];

/// Похоже ли на настоящее имя (предупреждаем: лучше псевдоним — так мы не храним персональные данные).
bool looksLikeRealName(String login) {
  final parts = login
      .toLowerCase()
      .split(RegExp(r'[^a-zа-яё]+'))
      .where((p) => p.isNotEmpty)
      .toList();
  if (parts.any(_firstNames.contains)) return true;
  final surname = parts.any((p) => p.length >= 5 && _surnameSuffixes.any(p.endsWith));
  return surname && parts.length >= 2;
}

/// Оценка стойкости пароля 0..4 (подсказка в интерфейсе; сервер проверяет минимум сам).
int passwordStrength(String password) {
  if (password.length < 10) return 0;
  var classes = 0;
  if (RegExp(r'[a-zа-яё]').hasMatch(password)) classes++;
  if (RegExp(r'[A-ZА-ЯЁ]').hasMatch(password)) classes++;
  if (RegExp(r'\d').hasMatch(password)) classes++;
  if (RegExp(r'[^\wа-яёА-ЯЁ]').hasMatch(password)) classes++;
  final unique = password.split('').toSet().length;
  var score = classes;
  if (password.length >= 14) score++;
  if (unique < 6) score = min(score, 1);
  return score.clamp(0, 4);
}

/// Достать код приглашения из QR: ссылка `doomich://invite/XXXX-XXXX`, `https://…/invite/XXXX-XXXX` или сам код.
String? inviteCodeFromQr(String raw) {
  final match = RegExp(r'invite/([A-Za-z0-9-]{6,32})').firstMatch(raw) ?? RegExp(r'^\s*([A-Za-z0-9]{4}-?[A-Za-z0-9]{4})\s*$').firstMatch(raw);
  return match?.group(1)?.toUpperCase();
}
