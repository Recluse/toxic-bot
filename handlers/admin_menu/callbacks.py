"""
handlers/admin_menu/callbacks.py — All callback_data string constants.

Using string constants (rather than raw literals scattered across files)
means a typo is caught at import time as a NameError, not silently
when a callback never fires.

Naming convention:  PREFIX:action:optional_param
"""

# --- Navigation ---
MENU_MAIN           = "menu:main"
MENU_EXIT           = "menu:exit"

# --- Submenus (open the submenu view) ---
MENU_TOXICITY       = "menu:toxicity"
MENU_FREQUENCY      = "menu:frequency"
MENU_COOLDOWN       = "menu:cooldown"
MENU_EXPLAIN_COOLDOWN = "menu:explain_cooldown"
MENU_CHAIN          = "menu:chain"
MENU_MIN_WORDS      = "menu:min_words"
MENU_USER_MGMT      = "menu:user_mgmt"
MENU_UNTOUCHABLES   = "menu:untouchables"

# --- Toxicity: set:toxicity:{1-5} ---
def SET_TOXICITY(level: int)   -> str: return f"set:toxicity:{level}"

# --- Frequency: individual increment/decrement + save ---
FREQ_MIN_UP         = "freq:min:up"
FREQ_MIN_DOWN       = "freq:min:down"
FREQ_MAX_UP         = "freq:max:up"
FREQ_MAX_DOWN       = "freq:max:down"
FREQ_SAVE           = "freq:save"

# --- Explain cooldown: individual increment/decrement + save ---
EXPLAIN_CD_DOWN     = "expcd:down"
EXPLAIN_CD_UP       = "expcd:up"
EXPLAIN_CD_SAVE     = "expcd:save"

# --- Cooldown: set:cooldown:{seconds} ---
def SET_COOLDOWN(seconds: int) -> str: return f"set:cooldown:{seconds}"

# --- Reply chain depth: set:chain:{val} ---
def SET_CHAIN(val: int)        -> str: return f"set:chain:{val}"

# --- Minimum words: set:min_words:{val} ---
def SET_MIN_WORDS(val: int)    -> str: return f"set:min_words:{val}"

# --- User management actions ---
RESET_CHAT          = "act:reset_chat"
RESET_CHAT_CONFIRM  = "act:reset_chat:confirm"

def RESET_USER(user_id: int)   -> str: return f"act:reset_user:{user_id}"
def VIEW_SUMMARY(user_id: int) -> str: return f"act:summary:{user_id}"
def UNTOUCHABLE_REMOVE(user_id: int) -> str: return f"act:untouchable_remove:{user_id}"

# --- Language selection (also used in first-run picker) ---
def SET_LANG(code: str)        -> str: return f"lang:set:{code}"

# ---------------------------------------------------------------------------
# Prefix matchers — used in router.py to route variable callbacks
# without enumerating every possible value.
# ---------------------------------------------------------------------------
PREFIX_SET_TOXICITY  = "set:toxicity:"
PREFIX_SET_COOLDOWN  = "set:cooldown:"
PREFIX_SET_CHAIN     = "set:chain:"
PREFIX_SET_MIN_WORDS = "set:min_words:"
PREFIX_RESET_USER    = "act:reset_user:"
PREFIX_VIEW_SUMMARY  = "act:summary:"
PREFIX_UNTOUCHABLE_REMOVE = "act:untouchable_remove:"
PREFIX_LANG_SET      = "lang:set:"
