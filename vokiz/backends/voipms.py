import requests
import urllib.parse

from vokiz import Error


def _e164_to_na(number):
    """Convert E.164 to North American number."""
    if not number.startswith("+1"):
        raise ValueError("Invalid number.")
    number = number[2:]
    if len(number) != 10 or not number.isnumeric():
        raise ValueError("Invalid number.")
    return number


def _na_to_e164(number):
    """Convert North American to E.164 number."""
    if len(number) != 10 or not number.isnumeric():
        raise ValueError("Invalid number.")
    return f"+1{number}"


class SMS:
    """A VOIP.ms short message service that can send and receive text messages."""

    base_url = "https://voip.ms/api/v1/rest.php"

    def __init__(self, username, password, did):
        self.username = username
        self.password = password
        self.did = did
        self.ping()  # ensure working

    def _request(self, method, **kwargs):
        url = f"{Client.base_url}?api_username={self.username}&api_password={self.password}&method={method}&content_type=json"
        if kwargs:
            url = f"{url}&{urllib.parse.urlencode(kwargs)}"
        response = requests.get(url)
        if response.status_code != 200:
            raise Error("Internal server error.")
        reply = response.json()
        if reply.get("status") != "success":
            raise Error("Internal server error.")
        return reply

    def ping(self):
        """Confirm connectivity to server."""
        self._request("getIP")

    def receive(self):
        """Receive next incoming text message."""
        result = None
        reply = self._request("getSMS", did=self.did)
        for sms in reply["sms"]:
            id = sms["id"]
            if sms["type"] == "1":  # incoming
                result = (_na_to_e164(sms["contact"]), sms["message"])
            self._request("deleteSMS", id=id)
            if result:
                return result

    def send(self, number, messages):
        """Send outgoing text message."""
        self._request(
            "sendSMS", did=self.did, dst=_e164_to_na(number), message=messsage
        )
