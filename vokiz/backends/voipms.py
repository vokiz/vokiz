"""VOIP.ms backend module."""

import requests
import urllib.parse

from vokiz.backends import BackendError


def _e164_to_na(number):
    """Convert E.164 to North American number."""
    if not number.startswith("+1"):
        raise BackendError("Invalid number")
    number = number[2:]
    if len(number) != 10 or not number.isnumeric():
        raise BackendError("Invalid number")
    return number


def _na_to_e164(number):
    """Convert North American to E.164 number."""
    if len(number) != 10 or not number.isnumeric():
        raise BackendError("Invalid number")
    return f"+1{number}"


class SMS:
    """A VOIP.ms short message service that can send and receive text messages."""

    base_url = "https://voip.ms/api/v1/rest.php"

    def __init__(self, username, password, did):
        self.username = username
        self.password = password
        self.did = did
        self.ping()  # ensure working

    def _request(self, method, expect=None, **kwargs):
        url = f"{SMS.base_url}?api_username={self.username}&api_password={self.password}&method={method}&content_type=json"
        if kwargs:
            url = f"{url}&{urllib.parse.urlencode(kwargs)}"
        response = requests.get(url)
        if response.status_code != 200:
            raise BackendError(f"Unexpected status_code: {response.status_code}")
        result = response.json()
        status = result["status"]
        if expect and status != expect:
            raise BackendError(f"Unexpected status: {status}")
        return result

    def ping(self):
        """Confirm connectivity to server."""
        self._request("getIP", "success")

    def receive(self):
        """Generator to iterate through incoming text messages."""
        response = self._request("getSMS", did=self.did)
        status = response["status"]
        if status == "no_sms":
            incoming = ()
        elif status == "success":
            incoming = response["sms"]
        else:
            raise BackendError(status)
        for sms in incoming:
            id = sms["id"]
            self._request("deleteSMS", "success", id=id)
            if sms["type"] == "1":  # incoming
                yield (_na_to_e164(sms["contact"]), sms["message"])

    def send(self, number, message):
        """Send outgoing text message."""
        return self._request(
            "sendSMS", "success", did=self.did, dst=_e164_to_na(number), message=message
        )
