"""Public execution failures whose messages are owned by the application."""


class AdmissionResponseError(Exception):
    code = "ADMITTANCE_INVALID_RESPONSE"
    public_message = "输入范围判断返回了无效结果，请重试；输入和草稿已保留"

    def __init__(self):
        super().__init__(self.public_message)
