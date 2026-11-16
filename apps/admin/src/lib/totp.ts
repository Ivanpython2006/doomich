/** Секрет из ссылки otpauth:// — на случай ручного ввода в приложение-аутентификатор. */
export function totpSecret(uri: string): string | null {
  try {
    return new URL(uri).searchParams.get('secret')
  } catch {
    return null
  }
}
