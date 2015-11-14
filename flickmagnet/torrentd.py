
import os
import time

import libtorrent
import sys

import binascii

from operator import attrgetter

status_names = ['queued', 'checking', 'downloading metadata', 'downloading', 'finished', 'seeding', 'allocating']

dht_routers = [
    ('router.utorrent.com', 6881),
    ('router.bittorrent.com', 6881),
    ('dht.transmissionbt.com', 6881),
    ('dht.aelitis.com', 6881)
]

dht_bootstrap_nodes = [
    ('bootstrap.ring.cx', 4222)
]

default_trackers = [
    'udp://tracker.openbittorrent.com:80',
    'udp://open.demonii.com:1337',
    'udp://tracker.coppersurfer.tk:6969',
    'udp://tracker.leechers-paradise.org:6969',
    'http://pow7.com/announce'
]

import inspect



def start(settings, db_connect, save_path):

    magnet_statuses = settings['cached_tables']['magnet_file_status']

    # start session
    session_handle = libtorrent.session()

    # print(session_handle.get_settings)

    # listen
    print('torrentd starting on port', settings['torrent_port'])
    session_handle.listen_on(settings['torrent_port'], settings['torrent_port'])

    # add some dht routers, if a search is ever made while the routing table is empty, those nodes will be used as backups
    for r in dht_routers:
        session_handle.add_dht_router(*r)

    # add some dht nodes, if a valid DHT reply is received, the node will be added to the routing table
    for r in dht_bootstrap_nodes:
        session_handle.add_dht_node(r)


    # already started by session() flags?

    # the listen port and the DHT port are attempted to be forwarded on local UPnP router devices
    # @todo dht_state should be saved on shutdown and passed in here:  http://libtorrent.org/reference-Session.html#id38
    #session_handle.start_dht()

    # the listen port and the DHT port are attempted to be forwarded on local UPnP router devices
    #session_handle.start_upnp()


    while True:


        #print()

        for alert in session_handle.pop_alerts():
            print('torrent alert:', alert)


        #session_status = session_handle.status()

        #print(
        #    'dht: ',
        #    '(down: ', session_status.dht_download_rate / 1000, ' kb/s up: ', session_status.dht_upload_rate / 1000, ' kB/s ',
        #    'nodes: ', session_status.dht_nodes, ') ',
        #    'dht_torrents: ', session_status.dht_torrents
        #)

        for torrent_handle in session_handle.get_torrents():

            print()
            print('status of torrent:', torrent_handle.info_hash())

            # dht_settings = session_handle.get_settings()

            torrent_status = torrent_handle.status()

            print(
                torrent_status.progress * 100, '% complete ',
                '(down: ', torrent_status.download_rate / 1000, ' kb/s up: ', torrent_status.upload_rate / 1000, ' kB/s ',
                'peers: ', torrent_status.num_peers, ') ',
                'state: ', status_names[torrent_status.state]

            )



        # print('trackers: ', torrent_handle.trackers())

        # print('torrent cleanup')
        # session_handle.remove_torrent(torrent_handle)

        process_queue(session_handle, save_path, db_connect(), magnet_statuses)

        time.sleep(3)

    # exit instead of returning to parent process
    os._exit(0)









# start downloading the torrent file immediately, with highest priority, starting at the byte_offset
def start_streaming_magnet_file(session_handle, save_path, btih, video_filename, magnet_file_id, db, byte_offset=0):

    # stop any other torrents
    # @todo only stop torrents for this user
    for torrent_handle in session_handle.get_torrents():
        torrent_handle.pause()


    # can't get add_torrent to work with infohash
    #
    # btih_bytes = binascii.unhexlify(btih)
    # btih_str = btih_bytes.decode('raw_unicode_escape')
    # infohash = libtorrent.sha1_hash(btih_bytes)
    #torrent_handle = session_handle.add_torrent({
    #    'save_path': save_path,
    #    'infohash': infohash
    #})

    # putting it in a magnet URL works
    torrent_handle = session_handle.add_torrent({
        'save_path': save_path,
        'url': 'magnet:?xt=urn:btih:' + btih,
        'storage_mode': libtorrent.storage_mode_t.storage_mode_allocate
    })

    # add some udp trackers
    for url in default_trackers:
        torrent_handle.add_tracker({
            'url': url
        })

    torrent_handle.force_dht_announce()
    torrent_handle.set_sequential_download(True)




    print('waiting for torrent metadata')

    # @todo timeout
    while torrent_handle.status().state<3:
        torrent_status = torrent_handle.status()
        print(status_names[torrent_status.state])
        time.sleep(3)

    torrent_info = torrent_handle.get_torrent_info()


    # assume the biggest file is the video payload
    # http://libtorrent.org/reference-Storage.html#file-entry
    biggest_file_entry = max(torrent_info.files(), key=attrgetter('size'))

    dbc = db.execute("""
UPDATE
    magnet_file
SET
    filename = ?
WHERE
    id = ?

""", [
    biggest_file_entry.path,
    magnet_file_id
])
    db.commit()


    # @todo only download the specified video_filename, not entire torrent

    # @todo start downloading at "byte_offset", eg. so the video player can seek ahead

    # @todo stop any other downloads

    #torrent_status = torrent_handle.status()






# process magnet_file actions
def process_queue(session_handle, save_path, db, magnet_statuses):

    # find videos queued to start streaming
    dbc = db.execute("""
SELECT
    magnet_file.*,
    magnet.btih
FROM
    magnet_file
JOIN
    magnet
        ON
            magnet.id = magnet_file.magnet_id
WHERE
    magnet_file.status_id = %d
""" % (
    magnet_statuses['start watching']
))

    for r in dbc.fetchall():
        # start watching
        print('start watching')
        start_streaming_magnet_file(session_handle, save_path, r['btih'], r['filename'], r['id'], db, r['stream_position'])
        dbc = db.execute("""
UPDATE
    magnet_file
SET
    status_id = %d
WHERE
    id = %d
""" % (
    magnet_statuses['watching'],
    r['id']
))
        db.commit()
