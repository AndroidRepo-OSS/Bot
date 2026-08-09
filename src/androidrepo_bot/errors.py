class ApplicationError(RuntimeError):
    pass


class RepositoryAccessError(ApplicationError):
    pass


class RepositoryNotFoundError(RepositoryAccessError):
    pass


class RateLimitError(RepositoryAccessError):
    pass


class ExternalServiceError(RepositoryAccessError):
    pass


class ExternalServiceTimeoutError(ExternalServiceError):
    pass


class GenerationError(ApplicationError):
    pass


class NotAndroidProjectError(GenerationError):
    pass


class MissingDownloadSourceError(GenerationError):
    pass
