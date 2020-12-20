import datetime
import http
import random

with open("words.txt", "r") as f:
    WORDS = f.read().split("\n")


def prepare_http_response(filename):
    with open(filename, "rb") as f:
        homepage = f.read()
        headers = [("Content-Type", "text/html"), ("Content-Length", str(len(homepage)))]
    
    return (http.HTTPStatus.OK, headers, homepage)


def pick_word():
    word = random.choice(WORDS)
    shuffled = "".join(random.sample(word, len(word)))
    return (word, shuffled)


def current_time():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def redis_publish(redis, sender, action):
    message = {
        "ip_address": sender,
        "action": action,
        "timestamp": current_time()
    }
    redis.publish_json("action-logs", message)