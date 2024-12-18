import requests
import os
import re
from dotenv import load_dotenv
from flask import Flask, request, redirect, render_template, session
from bsky_util import BlueskyUtil
from atproto import client_utils

load_dotenv(".env")

# FacebookのApp IDとシークレットキー
APP_ID = os.getenv("FACEBOOK_APP_ID")
APP_SECRET = os.getenv("FACEBOOK_APP_SECRET")
REDIRECT_URI = os.getenv("FACEBOOK_REDIRECT_URI")

app = Flask(__name__)
bsky_util = BlueskyUtil()

# ローカルネットワーク内で動かす想定なのでシークレットキーは直書き
app.secret_key = "local_secret_key"


def get_image_bytes(img_url: str) -> bytes:
    """画像URLから画像データを取得"""
    resp = requests.get(img_url)
    resp.raise_for_status()
    return resp.content


def message_to_textbuilder(message: str) -> client_utils.TextBuilder:
    """テキストに含まれるタグ情報を分離、タグとして設定する"""
    hashtags = re.findall(r"#\w+", message)
    clean_message = re.sub(r"#\w+", "", message).strip()

    text_builder = client_utils.TextBuilder().text(clean_message)
    for hashtag in hashtags:
        text_builder.text(" ").tag(hashtag, hashtag.lstrip("#"))
    return text_builder


def get_post_images(access_token: str) -> str:
    """最新投稿の画像URLリスト(imgタグに整形済み)を取得"""
    graph_api_url = "https://graph.facebook.com/v21.0/me/posts"
    params = {"access_token": access_token, "fields": "id,created_time"}
    response = requests.get(graph_api_url, params=params)
    if response.status_code == 200:
        posts = response.json()
    latest_post = (
        posts["data"][0] if "data" in posts and len(posts["data"]) > 0 else None
    )

    if latest_post:
        post_id = latest_post["id"]

        # 投稿の詳細を取得
        post_details_url = f"https://graph.facebook.com/v21.0/{post_id}"
        detail_params = {
            "access_token": access_token,
            "fields": "message,created_time,attachments",
        }
        detail_response = requests.get(post_details_url, params=detail_params)
        if detail_response.status_code == 200:
            detailed_post = detail_response.json()
            # 画像URLを取得
            if "attachments" in detailed_post:
                subattachments = detailed_post["attachments"]["data"][0][
                    "subattachments"
                ]["data"]
                image_urls = [
                    subattachment["media"]["image"]["src"]
                    for subattachment in subattachments
                    if "media" in subattachment and "image" in subattachment["media"]
                ]
                images_tag = ""
                for image_url in image_urls:
                    images_tag += '<img src="' + image_url + '" class="screenshot">'
                session["image_urls"] = image_urls
                return images_tag
    else:
        return None


@app.before_request
def make_session_permanent():
    session.permanent = True
    app.config.update(SESSION_COOKIE_SAMESITE="Lax")


# ログインURLの生成
@app.route("/")
def login():
    try:
        # 前回分のアクセストークンの取得を試行し、それが有効だったらそのまま画像取得＆フォーム表示
        access_token = session.get("access_token")
        graph_api_url = "https://graph.facebook.com/v21.0/me/posts"
        params = {"access_token": access_token, "fields": "id,created_time"}
        requests.get(graph_api_url, params=params)

        # トークンを使って画像取得＆
        images_tag = get_post_images(access_token)
        message = session.get("message", "")
        return render_template("form.html", images=images_tag, message=message)
    except:
        return redirect(
            f"https://www.facebook.com/v21.0/dialog/oauth?client_id={APP_ID}&redirect_uri={REDIRECT_URI}&state=your_state_value&scope=public_profile%2Copenid"
        )


# コールバックでアクセストークンを取得してフォーム表示
@app.route("/callback")
def callback():
    code = request.args.get("code")
    response = requests.get(
        f"https://graph.facebook.com/v21.0/oauth/access_token?client_id={APP_ID}&redirect_uri={REDIRECT_URI}&client_secret={APP_SECRET}&code={code}"
    )
    data = response.json()
    access_token = data.get("access_token")
    session["access_token"] = access_token

    images_tag = get_post_images(access_token)
    message = session.get("message", "")
    return render_template("form.html", images=images_tag, message=message)


# Blueskyに投稿
@app.route("/submit", methods=["POST"])
def submit():
    images = []
    for image_url in session.get("image_urls", []):
        images.append(get_image_bytes(image_url))

    session["message"] = request.form["message"]

    bsky_util.load_session()
    bsky_util.post_image(message_to_textbuilder(request.form["message"]), images=images)
    return render_template("result.html", result="success.", home_url="..")


if __name__ == "__main__":
    app.run(debug=True)
