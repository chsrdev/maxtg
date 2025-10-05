class BaseException(Exception):
    def __init__(self, error, title):
        super().__init__(f"{title} ({error})")
        self.error = error
        self.title = title

class VerifyCodeWrong(BaseException):
    pass

class UserNotFound(BaseException):
    pass
