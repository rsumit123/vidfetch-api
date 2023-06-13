import requests
import io
from flask import Flask, jsonify, request, send_file, make_response
from flask_cors import CORS
import urllib.request
import os
import boto3
from headers_cookies_data import headers, cookies, post_data
import xmltodict
from logging.config import dictConfig

dictConfig(
    {
        "version": 1,
        "formatters": {
            "default": {
                "format": "[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
            }
        },
        "handlers": {
            "wsgi": {
                "class": "logging.StreamHandler",
                "stream": "ext://flask.logging.wsgi_errors_stream",
                "formatter": "default",
            }
        },
        "root": {"level": "INFO", "handlers": ["wsgi"]},
    }
)

app = Flask(__name__)


app = Flask(__name__)
CORS(app)

bucket_name = "vidfetch-files"


def upload_video_to_s3(file_path, bucket_name, object_key):
    s3_client = boto3.client("s3")

    # Upload the video file to S3
    with open(file_path, "rb") as file:
        s3_client.upload_fileobj(file, bucket_name, object_key)


def generate_presigned_url(bucket_name, object_key, expiration=3600):
    """Generates presigned url"""
    s3_client = boto3.client("s3")

    # Generate a presigned URL for the video file
    presigned_url = s3_client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket_name,
            "Key": object_key,
            "ResponseContentDisposition": f'attachment; filename="vf_insta_video_{object_key}.mp4"',
        },
        ExpiresIn=expiration,
    )

    return presigned_url


def get_video_url(data):
    """Fetches video url from instagram"""

    try:
        data_dict = xmltodict.parse(
            data["data"]["xdt_api__v1__media__shortcode__web_info"]["items"][0][
                "carousel_media"
            ][0]["video_dash_manifest"]
        )

        video_url = data_dict["MPD"]["Period"]["AdaptationSet"][0]["Representation"][0][
            "BaseURL"
        ]

        return video_url
    except Exception as e:
        app.logger.error(
            f"Failed to fetch video from the second method too. Received data as {data}"
        )
        raise Exception(e)


@app.route("/video-id")
def get_video_id(post_url=None):
    """Fetches instagram video url, uploads the file to S3 and returns a video id"""
    try:
        if post_url is None:
            post_url = request.args.get("postUrl")
        short_code = post_url.split("https://")[1].split("/")[2]
        post_data["variables"] = '{"shortcode":' + '"' + short_code + '"}'

        response = requests.post(
            "https://www.instagram.com/api/graphql",
            cookies=cookies,
            headers=headers,
            data=post_data,
        )

        app.logger.info(
            f"{response.status_code} is the status code of instagram API request."
        )

        video_filename = str(short_code.replace("/", ""))

        # app.logger.debug(f'Received data -> {response.text}')

        data = response.json()

        # print(f"Received data {data}")

        try:
            video_url = data["data"]["xdt_api__v1__media__shortcode__web_info"][
                "items"
            ][0]["video_versions"][0]["url"]

        except Exception as e:
            app.logger.info(
                f"Fetching video url from second method, might be a facebook video."
            )
            video_url = get_video_url(data)

        app.logger.info(f"Received video_url {video_url}")

        filepath = f"/tmp/{video_filename}.mp4"

        urllib.request.urlretrieve(video_url, filepath)

        response = upload_video_to_s3(filepath, bucket_name, video_filename)

        app.logger.info("video uploaded successfully")

        if os.path.exists(filepath):
            os.remove(filepath)
            app.logger.info("Removed the file %s" % filepath)
        else:
            app.logger.info("Sorry, file %s does not exist." % filepath)

        return make_response(jsonify({"success": True, "video_id": video_filename, "status": 200}), 200)

    except Exception as e:
        app.logger.error(f"Error while generation of video id, {e}")
        return make_response(jsonify({"success": False, "error": str(e), "status": 500}), 500)


@app.route("/video")
def get_video_data():
    """Given a video id, generates and returns an S3 presigned url."""
    try:
        video_filename = request.args.get("videoId")

        presigned_url = generate_presigned_url(bucket_name, video_filename)

        return make_response(jsonify({"video_url": presigned_url, "status": 200}), 200)

    except Exception as e:
        app.logger.error(f"Error while fetching video from S3, {e}")

        return make_response(jsonify({"success": False, "error": str(e), "status": 500}), 500)


@app.route("/health")
def check_health():

    response = get_video_id(post_url="https://www.instagram.com/reels/CtBxeRULhqO/")
    print(response)
    # data = response.data()
    if (response.status_code==200):
        return make_response(jsonify({"status": "OK"}), 200)
    else:
        return make_response(jsonify({"status": "FAILED"}), 500)
    


@app.route("/")
def home():
    try:
        return {
            "success": True,
            "message": "Call /video-id?postUrl=instagramUrl with an instagram reel/post url to get video id and then call /video?videoId=videoId to get video.",
            "status": 200,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "status": 500}


if __name__ == "__main__":
    app.run(debug=True)
