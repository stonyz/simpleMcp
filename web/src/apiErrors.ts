/** Keep error identity and safe diagnostics until the UI renders its current language. */
export interface ErrorDiagnostic {
  type?: string;
  loc?: (string | number)[];
  msg?: string;
  code?: string;
  params?: Record<string, unknown>;
}
export class ApiError extends Error {
  constructor(
    message: string,
    readonly code?: string,
    readonly params: Record<string, unknown> = {},
    readonly diagnostics: ErrorDiagnostic[] = [],
  ) {
    super(message);
    this.name = 'ApiError';
  }
}
