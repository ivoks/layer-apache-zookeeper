from charms.reactive import set_state, when, when_not
from charms.reactive.helpers import any_file_changed, data_changed
from charmhelpers.core import hookenv
from charms.layer.zookeeper import Zookeeper, get_ip_for_interface
from jujubigdata.utils import DistConfig


@when_not('zookeeper.installed')
def install_zookeeper(*args):
    zk = Zookeeper()
    if zk.verify_resources():
        hookenv.status_set('maintenance', 'Installing Zookeeper')
        zk.install()
        zk.initial_config()
        set_state('zookeeper.installed')
        hookenv.status_set('maintenance', 'Zookeeper Installed')


@when('zookeeper.installed')
@when_not('zookeeper.started')
def start_zookeeper():
    zk = Zookeeper()
    zk.start()
    zk.open_ports()
    set_state('zookeeper.started')
    hookenv.status_set('active', 'Ready')


@when('zookeeper.started')
def restart_zookeeper_if_config_changed():
    """Restart Zookeeper if zoo.cfg has changed.

    As peers come and go, zoo.cfg will be updated. When that file changes,
    restart the Zookeeper service and set an appropriate status message.
    """

    # Possibly update bind address
    network_interface = hookenv.config().get('network_interface')
    if data_changed("zookeeper.bind_address", network_interface):
        zk = Zookeeper()
        zk.update_bind_address()

    zoo_cfg = DistConfig().path('zookeeper_conf') / 'zoo.cfg'
    if any_file_changed([zoo_cfg]):
        hookenv.status_set('maintenance', 'Server config changed: restarting Zookeeper')
        zk = Zookeeper()
        zk.stop()
        zk.start()
        zk_count = int(zk.get_zk_count())
        extra_status = ""
        if zk_count < 3:
            extra_status = ": less than 3 is suboptimal"
        elif (zk_count % 2 == 0):
            extra_status = ": even number is suboptimal"
        hookenv.status_set('active', 'Ready (%d zk units%s)' % (zk_count, extra_status))
    else:
        # Make sure zookeeper is running in any case
        zk = Zookeeper()
        zk.start()
        zk.open_ports()


@when('zookeeper.started', 'config.changed.rest')
def rest_config():
    hookenv.status_set('maintenance', 'Updating REST service')
    zk = Zookeeper()
    config = hookenv.config()
    if config['rest']:
        zk.start_rest()
    else:
        zk.stop_rest()
    hookenv.status_set('active', 'Ready')


@when('zookeeper.started', 'zkpeer.joined')
def quorum_add(zkpeer):
    """Add a zookeeper peer.

    Add the unit that just joined, restart Zookeeper, and remove the
    '.joined' state so we don't fall in here again (until another peer joins).
    """
    nodes = zkpeer.get_nodes()  # single node since we dismiss .joined below
    zk = Zookeeper()
    zk.increase_quorum(nodes)
    restart_zookeeper_if_config_changed()
    zkpeer.dismiss_joined()


@when('zookeeper.started', 'zkpeer.departed')
def quorum_remove(zkpeer):
    """Remove a zookeeper peer.

    Remove the unit that just departed, restart Zookeeper, and remove the
    '.departed' state so we don't fall in here again (until another peer leaves).
    """
    nodes = zkpeer.get_nodes()  # single node since we dismiss .departed below
    zk = Zookeeper()
    zk.decrease_quorum(nodes)
    restart_zookeeper_if_config_changed()
    zkpeer.dismiss_departed()


@when('zookeeper.started', 'zkclient.joined')
def serve_client(client):
    config = DistConfig()
    port = config.port('zookeeper')
    rest_port = config.port('zookeeper-rest')
    host = None
    network_interface = hookenv.config().get('network_interface')
    if network_interface:
        host = get_ip_for_interface(network_interface)
    client.send_connection(port, rest_port, host)
