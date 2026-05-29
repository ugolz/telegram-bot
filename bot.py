import os.path, pickle, hashlib, logging, time, sys, traceback, random, unicodedata, os, gc, json, urllib.error, urllib.parse, urllib.request, socket, requests, shlex

# Legge il token dalla variabile d'ambiente invece che hardcodato
T = os.environ.get("TELEGRAM_BOT_TOKEN", "")
if not T:
    raise RuntimeError("TELEGRAM_BOT_TOKEN non impostato")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

custom_urlopen = lambda u,**kw:urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': UA}),**kw)

class TelegramBot():
    class attribute_dict():
        def __init__(self, data):
            self.__data__ = data
        def __getattr__(self, index):
            if index == "__data__": return object.__getattr__(self, "__data__")
            try:
                return self.__getitem__(index)
            except KeyError:
                raise AttributeError
        def __getitem__(self, index):
            return self.__data__[index]
        def __setattr__(self, index, value):
            if index == "__data__": return object.__setattr__(self, "__data__", value)
            self.__setitem__(index)
        def __setitem__(self, index, value):
            self.__data__[index] = value
        def __delattr__(self, index, value):
            if index == "__data__": return object.__delattr__(self, "__data__", value)
            self.__delitem__(index)
        def __delitem__(self, index, value):
            del self.__data__[index]
        def __repr__(self):
            return repr(self.__data__)
        def __iter__(self):
            return iter(self.__data__)
        def __len__(self):
            return len(self.__data__)
        def keys(self):
            return self.__data__.keys()
        def has(self, key):
            return key in self.__data__.keys() and self.__data__[key] != None
    def __init__(self, token):
        self.token = token
        self.retry = 0
    def __getattr__(self, attr):
        return self.func_wrapper(attr)
    def get_url(self, fname, **kw):
        url_par={}
        for key in kw.keys():
            if kw[key] != None:
                url_par[key] = urllib.parse.quote_plus(TelegramBot.escape(kw[key]))
        return (url_par,("https://api.telegram.org/bot" + self.token + "/" + (fname.replace("__UNSAFE","") if fname.endswith("__UNSAFE") else fname) + "?" +
                "&".join(map(lambda x:x+"="+url_par[x],url_par.keys()))))
    @staticmethod
    def default_urlopen(u):
        with custom_urlopen(u,timeout=90) as f:
            raw = f.read().decode('utf-8')
        return raw
    def func_wrapper(self, fname):
        def func(self, unsafe, _urlopen_hook=None, **kw):
            if _urlopen_hook is None:
                _urlopen_hook = TelegramBot.default_urlopen
            url_par, url = self.get_url(fname, **kw)
            RETRY = True
            while RETRY:
                try:
                    raw = _urlopen_hook(url)
                    RETRY = False
                except urllib.error.HTTPError as e:
                    if "bad request" in str(e).lower() and not unsafe:
                        print(fname, url)
                        print(json.dumps(url_par))
                        print(e.read().decode('utf-8'))
                        traceback.print_exc()
                        return
                    elif "forbidden" in str(e).lower() and not unsafe:
                        print(fname, url)
                        print(json.dumps(url_par))
                        print(e.read().decode('utf-8'))
                        traceback.print_exc()
                        return
                    else:
                        raise e
                except socket.timeout:
                    if unsafe:
                        raise ValueError("timeout")
                    else:
                        print("timeout!")
                        time.sleep(1)
                except BaseException as e:
                    print(str(e))
                    time.sleep(0.5)
                    if "too many requests" in str(e).lower():
                        self.retry += 1
                        time.sleep(self.retry * 5)
                    elif "unreachable" in str(e).lower() or "bad gateway" in str(e).lower() or "name or service not known" in str(e).lower() or "network" in str(e).lower() or "handshake operation timed out" in str(e).lower():
                        time.sleep(3)
                    elif "bad request" in str(e).lower() and not unsafe:
                        print(fname, url)
                        print(json.dumps(url_par))
                        traceback.print_exc()
                        return
                    elif "forbidden" in str(e).lower() and not unsafe:
                        print(fname, url)
                        print(json.dumps(url_par))
                        traceback.print_exc()
                        return
                    else:
                        raise e
            self.retry = 0
            return TelegramBot.attributify(json.loads(raw))
        return lambda **kw:func(self,fname.endswith("__UNSAFE"),**kw)
    @staticmethod
    def escape(obj):
        if type(obj) == str:
            return obj
        else:
            return json.dumps(obj).encode('utf-8')
    @staticmethod
    def attributify(obj):
        if type(obj)==list:
            return list(map(TelegramBot.attributify,obj))
        elif type(obj)==dict:
            d = obj
            for k in d.keys():
                d[k] = TelegramBot.attributify(d[k])
            return TelegramBot.attribute_dict(d)
        else:
            return obj

groups = {}

ALLOWABLE = ["Lc","Ll","Lm","Lo","Lt","Lu","Nd","Nl","No"]
COMMON_T = 0
SPLIT_LINES = False
LAST_USER = {}
MY_USERNAME = ""
Restart = False

try:
    from urllib.error import URLError
except ImportError:
    from urllib2 import URLError

def save(reason):
    print("SAVING ", reason)
    for key in groups:
        save_group(key)
    print("SAVED")

bot = TelegramBot(T)
MY_USERNAME = bot.getMe().result.username.lower()

# Crea la cartella markov se non esiste
os.makedirs("markov", exist_ok=True)

gcache = []
max_cache_size = 10
gc_every_unload = 30
gc_counter = gc_every_unload
last_msg_id = 0

def addMessage(message, g):
    w = [""] + message.lower().split(" ") + [""]
    for i in range(1,len(w)):
        lw = "".join(filter(lambda x:(unicodedata.category(x) in ALLOWABLE),w[i-1]))
        nw = w[i]
        if len(lw) < 50 and len(nw) < 50:
            if lw not in g.keys():
                g[lw] = []
            g[lw].append(nw)

def limit(s):
    t = " ".join(s.split(" ")[:50])
    return t[:400]

def load_group(chat_id):
    global gcache
    try:
        with open("markov/chat_" + str(chat_id) + ".dat", "rb") as f:
            groups[chat_id] = pickle.load(f)
        gcache.append(chat_id)
    except KeyboardInterrupt as e:
        raise e
    except:
        pass
    check_cache()

def check_cache():
    global gcache
    while len(gcache) > max_cache_size:
        unload_group(gcache[0])

def unload_group(chat_id):
    global gcache, gc_counter
    try:
        with open("markov/chat_" + str(chat_id) + ".dat", "wb") as f:
            pickle.dump(groups[chat_id], f)
            groups[chat_id] = None
            del groups[chat_id]
        gcache.remove(chat_id)
        gc_counter -= 1
        if gc_counter < 1:
            gc_counter = gc_every_unload
            gc.collect()
    except KeyboardInterrupt as e:
        raise e
    except:
        pass

def save_group(chat_id):
    try:
        with open("markov/chat_" + str(chat_id) + ".dat", "wb") as f:
            pickle.dump(groups[chat_id], f)
    except:
        pass

tried_to = 0
saferes = True
OFF = 0

try:
    while True:
        tried_to += 1
        print("poll " + str(time.time()), end=":")
        saferes = False
        try:
            updates = bot.getUpdates__UNSAFE(offset=OFF, timeout=5).result
        except KeyboardInterrupt as e:
            print("E")
            raise e
        except BaseException as e:
            print("0")
            if str(e).strip().lower() != "timeout":
                print("poll failed: ", e)
            continue
        print(len(updates), end="")
        print("(" + str(OFF) + ")")
        for update in updates:
            last_msg_id = update.update_id
            OFF = update.update_id + 1
            if not update.has("message"):
                continue
            if update.message == None:
                continue
            chat_id = update.message.chat.id
            chat_type = update.message.chat.type
            if update.message.has("migrate_from_chat_id"):
                nid = update.message.chat.id
                oid = update.message.migrate_from_chat_id
                if oid == nid:
                    continue
                if oid in gcache:
                    unload_group(oid)
                try:
                    os.rename("markov/chat_" + str(oid) + ".dat", "markov/chat_" + str(nid) + ".dat")
                except:
                    pass
                continue
            if update.message.has("text"):
                message = update.message.text
            else:
                message = ""
            replyto = update.message.message_id
            if update.message.has("from"):
                user = update.message["from"].id
            else:
                user = -1
            admbypass = False
            try:
                admbypass = admbypass or update.message.chat.all_members_are_administrators
            except:
                pass

            if chat_id not in gcache:
                load_group(chat_id)

            if chat_id not in groups.keys():
                groups[chat_id] = {}
                gcache.append(chat_id)
                check_cache()

            g = groups[chat_id]
            if g == None:
                groups[chat_id] = {}
                g = {}
            if 0 not in g.keys(): g[0] = 1
            if 1 not in g.keys(): g[1] = "en"
            if 2 not in g.keys(): g[2] = 100
            if 3 not in g.keys(): g[3] = True
            if 4 not in g.keys(): g[4] = 10000

            curtime = time.time()
            t = str(user) + ":" + str(chat_id)

            if len(message) < 1:
                continue
            if message[0] == "/":
                rcmd = message.split(" ")[0].split("@")[0]
                if "@" in message.split(" ")[0]:
                    cmdtarget = message.split(" ")[0].split("@")[1]
                    if cmdtarget.lower() != MY_USERNAME:
                        continue
                cmd = rcmd.lower()
                if cmd == "/markov" or cmd == "/pablitoo":
                    if t in LAST_USER.keys():
                        if (curtime - LAST_USER[t]) < g[0]:
                            continue
                    LAST_USER[t] = curtime
                    tries_o = 0
                    if "" in g.keys():
                        while True:
                            tries_o += 1
                            words = []
                            word = ""
                            if random.randint(0,10) < 5:
                                word = random.choice(list(filter(lambda x:type(x)==str, g.keys())))
                            else:
                                word = random.choice(g[word])
                            while word != "" and len(words) < min(g[4], 100):
                                words.append(word)
                                word = "".join(filter(lambda x:(unicodedata.category(x) in ALLOWABLE), word)).lower()
                                if word not in g.keys():
                                    word = ""
                                else:
                                    word = random.choice(g[word])
                            msg = " ".join(words)
                            if len(msg) > 0: break
                            if tries_o > 1000: break
                        # cancella il messaggio di trigger
                        try:
                            del_url = f"https://api.telegram.org/bot{T}/deleteMessage?chat_id={chat_id}&message_id={replyto}"
                            urllib.request.urlopen(urllib.request.Request(del_url, headers={'User-Agent': UA}), timeout=10)
                        except:
                            pass
                        try:
                            bot.sendMessage(chat_id=chat_id, text=msg)
                        except KeyboardInterrupt as e:
                            raise e
                        except:
                            pass
                    else:
                        try:
                            bot.sendMessage(chat_id=chat_id, text="[Chain is empty]", reply_to_message_id=replyto)
                        except:
                            pass
                if cmd == "/markovclear":
                    if t in LAST_USER.keys():
                        if (curtime - LAST_USER[t]) < 1:
                            continue
                    try:
                        st = bot.getChatMember(chat_id=chat_id, user_id=user).result.status
                        if chat_type in ["group","supergroup","channel"] and not admbypass and (st != "administrator" and st != "creator"):
                            continue
                    except:
                        pass
                    checkhash = hashlib.md5((str(chat_id)+str(user)+str(time.time()//1000)).encode("utf-8")).hexdigest()[:12].upper()
                    what = ""
                    try:
                        what = message.split(" ")[1].upper()
                    except:
                        pass
                    if what == checkhash:
                        groups[chat_id] = {}
                        save_group(chat_id)
                        bot.sendMessage(chat_id=chat_id, text="[Messages cleared]", reply_to_message_id=replyto)
                    else:
                        bot.sendMessage(chat_id=chat_id, text="[Copy this to confirm]\n/markovclear " + checkhash, reply_to_message_id=replyto)
                if cmd == "/markovpause":
                    try:
                        st = bot.getChatMember(chat_id=chat_id, user_id=user).result.status
                        if chat_type in ["group","supergroup","channel"] and not admbypass and (st != "administrator" and st != "creator"):
                            continue
                    except:
                        pass
                    g[3] = False
                    save_group(chat_id)
                    bot.sendMessage(chat_id=chat_id, text="[Reading paused]", reply_to_message_id=replyto)
                if cmd == "/markovresume":
                    try:
                        st = bot.getChatMember(chat_id=chat_id, user_id=user).result.status
                        if chat_type in ["group","supergroup","channel"] and not admbypass and (st != "administrator" and st != "creator"):
                            continue
                    except:
                        pass
                    g[3] = True
                    save_group(chat_id)
                    bot.sendMessage(chat_id=chat_id, text="[Reading resumed]", reply_to_message_id=replyto)
                if cmd == "/markovmaxwords":
                    try:
                        st = bot.getChatMember(chat_id=chat_id, user_id=user).result.status
                        if chat_type in ["group","supergroup","channel"] and not admbypass and (st != "administrator" and st != "creator"):
                            continue
                    except:
                        pass
                    t2 = " ".join(message.split(" ")[1:]).strip()
                    if len(t2) < 1:
                        bot.sendMessage(chat_id=chat_id, text="[Usage: /markovmaxwords words]", reply_to_message_id=replyto)
                        continue
                    try:
                        v = int(t2)
                    except:
                        bot.sendMessage(chat_id=chat_id, text="[Usage: /markovmaxwords words]", reply_to_message_id=replyto)
                        continue
                    if v < 1 or v > 120:
                        bot.sendMessage(chat_id=chat_id, text="[Limit for words is 1-120]", reply_to_message_id=replyto)
                        continue
                    g[4] = v
                    save_group(chat_id)
                    bot.sendMessage(chat_id=chat_id, text="[Maximum words set]", reply_to_message_id=replyto)
            elif message[0] != "/":
                if g[3]:
                    if SPLIT_LINES:
                        for line in message.split("\n"):
                            addMessage(line, g)
                    else:
                        addMessage(message, g)
                saferes = True
        time.sleep(0.02)
except KeyboardInterrupt as e:
    save("Quit")
except BaseException as e:
    save("Exception")
    traceback.print_exc()