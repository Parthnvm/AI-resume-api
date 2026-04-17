"""
Firebase Auth REST API helper.
Calls Firebase Identity Toolkit endpoints — no Firebase SDK needed,
only the `requests` library (already in requirements.txt).
"""
import os
import requests

_API_KEY = None


def _get_api_key():
    global _API_KEY
    if _API_KEY is None:
        _API_KEY = os.environ.get('FIREBASE_API_KEY', '')
    if not _API_KEY:
        raise RuntimeError(
            "FIREBASE_API_KEY is not set. "
            "Add it to your .env file — get it from Firebase Console → Project Settings → Web API Key."
        )
    return _API_KEY


def _firebase_post(endpoint: str, payload: dict) -> dict:
    """POST to a Firebase Auth REST endpoint, raise on error."""
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:{endpoint}?key={_get_api_key()}"
    resp = requests.post(url, json=payload, timeout=10)
    data = resp.json()
    if not resp.ok:
        # Firebase sometimes appends detail after ' : ' e.g. 'INVALID_LOGIN_CREDENTIALS : reason'
        raw_msg = data.get('error', {}).get('message', 'UNKNOWN_ERROR')
        # Normalise to just the base error code (everything before the first ' :')
        error_code = raw_msg.split(' :')[0].strip()
        raise FirebaseAuthError(error_code)
    return data


class FirebaseAuthError(Exception):
    """Maps Firebase REST error codes to user-friendly messages."""
    MESSAGES = {
        'EMAIL_EXISTS':              'An account with this email already exists.',
        'INVALID_EMAIL':             'Invalid email address.',
        'WEAK_PASSWORD':             'Password must be at least 6 characters.',
        'EMAIL_NOT_FOUND':           'No account found with that email.',
        'INVALID_PASSWORD':          'Incorrect password.',
        'INVALID_LOGIN_CREDENTIALS': 'Invalid email or password.',
        'USER_DISABLED':             'This account has been disabled.',
        'TOO_MANY_ATTEMPTS_TRY_LATER': 'Too many attempts. Please try again later.',
    }

    def __init__(self, code: str):
        # Normalise code in case a raw message string was passed directly
        self.code = code.split(' :')[0].strip()
        super().__init__(self.MESSAGES.get(self.code, 'Authentication error. Please try again.'))


def firebase_register(email: str, password: str) -> dict:
    """Create a new Firebase user. Returns {localId, idToken, email}."""
    return _firebase_post('signUp', {
        'email': email,
        'password': password,
        'returnSecureToken': True,
    })


def firebase_login(email: str, password: str) -> dict:
    """Sign in an existing Firebase user. Returns {localId, idToken, email}."""
    return _firebase_post('signInWithPassword', {
        'email': email,
        'password': password,
        'returnSecureToken': True,
    })


def firebase_update_password(id_token: str, new_password: str) -> dict:
    """Update password for the authenticated user (via their ID token)."""
    return _firebase_post('update', {
        'idToken': id_token,
        'password': new_password,
        'returnSecureToken': True,
    })


def firebase_send_password_reset(email: str) -> None:
    """
    Ask Firebase to send a password-reset email.
    Silently succeeds even if the email isn't registered (prevents enumeration).
    """
    try:
        _firebase_post('sendOobCode', {
            'requestType': 'PASSWORD_RESET',
            'email': email,
        })
    except FirebaseAuthError as e:
        # EMAIL_NOT_FOUND is acceptable — don't leak whether the email exists
        if e.code != 'EMAIL_NOT_FOUND':
            raise
