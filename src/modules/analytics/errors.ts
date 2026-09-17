export class DataUnavailableError extends Error {
  constructor(
    message: string,
    readonly code: string,
  ) {
    super(message)
    this.name = "DataUnavailableError"
  }
}
