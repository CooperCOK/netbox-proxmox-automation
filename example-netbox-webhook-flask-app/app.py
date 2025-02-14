import logging
import json
import yaml

from datetime import datetime

# adapted from: https://majornetwork.net/2019/10/webhook-listener-for-netbox/

from helpers.netbox_proxmox import NetBoxProxmoxHelper

from flask import Flask, request, jsonify
from flask_restx import Api, Resource, fields

VERSION = '1.1.0'

app_config_file = 'app_config.yml'

with open(app_config_file) as yaml_cfg:
    try:
        app_config = yaml.safe_load(yaml_cfg)
    except yaml.YAMLError as exc:
        print(exc)

if not 'netbox_webhook_name' in app_config:
    raise ValueError(f"'netbox_webhook_name' missing in {app_config_file}")

app = Flask(__name__)
api = Api(app, version="1.0.0", title="NetBox-Proxmox Webhook Listener",
        description="NetBox-Proxmox Webhook Listener")
ns = api.namespace(app_config['netbox_webhook_name'])

# set debug (enabled/disabled)
DEBUG = False

if app.debug:
    DEBUG = True


APP_NAME = "netbox-proxmox-webhook-listener"

logger = logging.getLogger(APP_NAME)
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s: %(message)s")
file_logging = logging.FileHandler("{}.log".format(APP_NAME))
file_logging.setFormatter(formatter)
logger.addHandler(file_logging)

webhook_request = api.model("Webhook request from NetBox", {
    'username': fields.String,
    'data': fields.Raw(description="Object data from NetBox"),
    'event': fields.String,
    'timestamp': fields.String,
    'model': fields.String,
    'request_id': fields.String,
})

# For session logging, c/o sol1
session = {
  'name': "example-netbox-webhook-flask-app",
  'version': VERSION,
  'version_lastrun': VERSION,
  'server_start': "",
  'status': {
    'requests': 0,
    'last_called': ""
  },
}


@ns.route("/status/", methods=['GET'])
class WebhookListener(Resource):
    @ns.expect(webhook_request)

    def get(self):
        _session = session.copy()
        _session['version_lastrun'] = VERSION
        _session['status']['requests'] += 1
        _session['status']['last_called'] = datetime.now()
        logger.info(f"{request.full_path}, {request.remote_addr}, Status request with data {request.get_data()}")
        return jsonify(_session)


# For handling event rules
@ns.route("/")
class WebhookListener(Resource):
    @ns.expect(webhook_request)
    def post(self):
        try:
            webhook_json_data = request.json
        except:
            webhook_json_data = {}

        logger.info("{}".format(webhook_json_data))

        if not webhook_json_data or "model" not in webhook_json_data or "event" not in webhook_json_data:
            return {"result":"invalid input"}, 400

        if DEBUG:
            print("INCOMING DATA FOR WEBHOOK", webhook_json_data)

        if 'proxmox_node' in webhook_json_data['data']['custom_fields']:
            proxmox_node = webhook_json_data['data']['custom_fields']['proxmox_node']
        else:
            proxmox_node = app_config['proxmox_api_config']['node']


        tc = NetBoxProxmoxHelper(app_config, proxmox_node)


        if webhook_json_data['event'] == 'created' and webhook_json_data['model'] == 'virtualmachine' and webhook_json_data['data']['status']['value'] == 'staged':
            tc.proxmox_clone_vm(webhook_json_data)
        elif webhook_json_data['event'] == 'updated' and webhook_json_data['model'] == 'virtualmachine' and webhook_json_data['data']['status']['value'] == 'staged':
            tc.proxmox_update_vm_resources(webhook_json_data)

            if webhook_json_data['data']['primary_ip'] and webhook_json_data['data']['primary_ip']['address']:
                tc.proxmox_set_ipconfig0(webhook_json_data)

            if 'proxmox_public_ssh_key' in webhook_json_data['data']['custom_fields'] and webhook_json_data['data']['custom_fields']['proxmox_public_ssh_key']:
                tc.proxmox_set_ssh_public_key(webhook_json_data) 
        elif webhook_json_data['event'] == 'updated' and webhook_json_data['model'] == 'virtualmachine' and webhook_json_data['data']['status']['value'] == 'offline':
            tc.proxmox_stop_vm(webhook_json_data)
        elif webhook_json_data['event'] == 'updated' and webhook_json_data['model'] == 'virtualmachine' and webhook_json_data['data']['status']['value'] == 'active':
            tc.proxmox_start_vm(webhook_json_data)
        elif webhook_json_data['event'] == 'deleted' and webhook_json_data['model'] == 'virtualmachine':
            tc.proxmox_delete_vm(webhook_json_data)

        # disk stuff
        if webhook_json_data['event'] == 'created' and webhook_json_data['model'] == 'virtualdisk':
            tc.proxmox_add_disk(webhook_json_data)
        elif webhook_json_data['event'] == 'updated' and webhook_json_data['model'] == 'virtualdisk':
            tc.proxmox_resize_disk(webhook_json_data)
        elif webhook_json_data['event'] == 'deleted' and webhook_json_data['model'] == 'virtualdisk':
            tc.proxmox_delete_disk(webhook_json_data)

        return {"result":"ok"}, 200


if __name__ == "__main__":
    app.run(host="0.0.0.0")
