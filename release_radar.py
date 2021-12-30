#!/bin/python3

import argparse
import datetime
import getpass
import logging
import os
import sys
import spotipy

from spotipy.oauth2 import SpotifyClientCredentials, SpotifyOAuth


MAX_ITEMS = 50
MAX_SET_ITEMS = 20


##
# Classes to model the Spotify libary:
##


class Artist:
    def __init__(self, id, name, popularity=None):
        self.id = id
        self.name = name
        self.popularity = popularity
        self.albums = None

    def get_albums(self, spotify):
        if self.albums != None:
            return self.albums

        resAlbums = []

        totalAlbums = -1
        offset = 0
        i = 0

        while i < totalAlbums or totalAlbums < 0:
            logging.debug("Requesting page of albums of artist \"" + self.name + "\"...")
            results = spotify.artist_albums(artist_id=self.id, limit = MAX_ITEMS, offset=offset)
            logging.debug("Received page of albums.")

            offset = offset + len(results["items"])
            assert results["limit"] == MAX_ITEMS

            totalAlbums = results["total"]

            for item in results["items"]:
                album = Album(item["id"], item["name"], [self], item["release_date"], item["release_date_precision"])
                resAlbums.append(album)
                i += 1

        self.albums = resAlbums
        return resAlbums

    def get_albums_with_tracks(self, spotify):
        if self.albums != None:
            complete = True
            for a in self.albums:
                if self.albums.tracks == None:
                    complete = False
            if complete:
                return self.albums
        else:
            self.get_albums(spotify)

        completeAlbumIdList = []
        for alb in self.albums:
            completeAlbumIdList.append(alb.id)
        
        resAlbumsList = []

        totalAlbums = len(completeAlbumIdList)
        offset = 0
        i = 0

        while i < totalAlbums:
            logging.debug("Requesting page of complete albums of artist \"" + self.name + "\"...")
            results = spotify.albums(completeAlbumIdList[offset:(offset+MAX_SET_ITEMS)])
            logging.debug("Received page of complete albums.")
            offset += MAX_SET_ITEMS

            for item in results["albums"]:
                # Create list of artists:
                artists = []
                for art in item["artists"]:
                    artists.append(Artist(art["id"], art["name"]))
                album = Album(item["id"], item["name"], artists, item["release_date"], item["release_date_precision"])
                album.type = item["album_type"]
                album.tracks = []
                # Add tracks:
                for tr in item["tracks"]["items"]:
                    # Create list of artists:
                    trArtists = []
                    for art in tr["artists"]:
                        trArtists.append(Artist(art["id"], art["name"]))
                    album.tracks.append(Track(tr["id"], tr["name"], album, trArtists))
                    
                resAlbumsList.append(album)
                i += 1

        self.albums = resAlbumsList
        return resAlbumsList


class Album:
    def __init__(self, id, name, artists, release_date, release_date_precision):
        self.id = id
        self.name = name
        self.artists = artists
        self.tracks = None
        self.type = None

        if release_date_precision == "day":
            self.release_date = datetime.datetime.strptime(release_date, "%Y-%m-%d")
        elif release_date_precision == "year":
            self.release_date = datetime.datetime.strptime(release_date, "%Y")
        else:
            logging.error("Could not parse release date because of unknown precision.\nDate: "
                    + release_date + "\nPrec: " + release_date_precision)
            exit(1)

    def is_collection(self):
        return self.type == "compilation" or (len(self.artists) == 1 and self.artists[0].id == "0LyfQWJT6nXafLPZqxe9Of")

    def is_done_by_artist(self, artistId):
        for artist in self.artists:
            if artist.id == artistId:
                return True
        return False

    def get_tracks(self, spotifyAccess):
        if self.tracks != None:
            return self.tracks

        res = []

        logging.debug("Requesting first page of tracks of album \"" + self.name + "\"...")
        resultPart = spotifyAccess.album_tracks(self.id, limit=MAX_ITEMS, offset=0)
        logging.debug("Received first page of tracks.")
        while resultPart:
            for tr in resultPart["items"]:
                artists = []
                for art in tr["artists"]:
                    artists.append(Artist(art["id"], art["name"]))
                res.append(Track(tr["id"], tr["name"], self, artists))
            if resultPart["next"]:
                logging.debug("Requesting next page of tracks.")
                resultPart = spotifyAccess.next(resultPart)
                logging.debug("Received next page of tracks.")
            else:
                resultPart = None

        self.tracks = res
        return res


class Track:
    def __init__(self, id, name=None, album=None, artists=None):
        self.id = id
        self.name = name
        self.album = album
        self.artists = artists

    def is_done_by_artist(self, artistId):
        # TODO: self.artist or self.album may be None
        for artist in self.artists:
            if artist.id == artistId:
                return True
        return False


    def __eq__(self, other):
        return isinstance(other, Track) and self.id == other.id

    def __hash__(self):
        return hash(self.id)

    def __str__(self):
        return "Track {\n\tid: %s,\n\tname: %s\n}" % (self.id, self.name)
    def __repr__(self):
        return str(self)


class Playlist:
    def __init__(self, id, name=None, tracks=None):
        self.id = id
        self.name = name
        self.tracks = tracks


    def by_name(spotifyAccess, name):
        playlists = get_complete_list(lambda offset:
                spotifyAccess.current_user_playlists(offset=offset, limit=MAX_ITEMS))

        for item in playlists:
            if item["name"] == name:
                return Playlist(item["id"], name=name)

        return None


    def create_playlist(spotifyAccess, name, user_id=None):
        if user_id == None:
            # Get current user:
            logging.debug("Requesting current user...")
            user_id = spotifyAccess.current_user()["id"]
            logging.debug("Received current user.")

        response = spotifyAccess.user_playlist_create(user_id, name, public=False)
        return Playlist(response["id"], name, [])


    def get_tracks(self, spotifyAccess):
        if self.tracks == None:
            self.tracks = []
            track_items = get_complete_list(
                    lambda offset: spotifyAccess.playlist_items(self.id,
                        limit=MAX_ITEMS,
                        offset=offset,
                        fields="total,items(track.id)"))
            for item in track_items:
                self.tracks.append(Track(item["track"]["id"]))

        return self.tracks

    
    def update_tracks(self, spotifyAccess, tracks):
        self.tracks = tracks
        spotifyAccess.playlist_replace_items(self.id, map(lambda tr: tr.id, tracks))


    def __str__(self):
        return "Playlist {\n\tid: %s,\n\tname: %s\n}" % (self.id, self.name)
    def __repr__(self):
        return str(self)


##
# Functions to handle functions on the libary:
##


def get_complete_list(get_page):
    res = []
    offset = 0

    page = get_page(offset)
    res.extend(page["items"])
    offset += len(page["items"])

    list_length = page["total"]
    while offset < list_length:
        page = get_page(offset)
        res.extend(page["items"])
        offset += len(page["items"])

    return res


def get_followed_artists(spotifyAccess):
    totalFollowed = -1
    lastId = None
    i = 0

    res = []

    while i < totalFollowed or totalFollowed < 0:
        logging.debug("Requesting page of followed artists...")
        results = spotifyAccess.current_user_followed_artists(limit = MAX_ITEMS, after=lastId)
        logging.debug("Received page of followed artists.")

        lastId = results["artists"]["cursors"]["after"]
        assert lastId == results["artists"]["items"][-1]["id"] or (len(results["artists"]["items"]) < MAX_ITEMS and lastId == None)
        assert results["artists"]["limit"] == MAX_ITEMS

        if totalFollowed == -1:
            totalFollowed = results["artists"]["total"]
        else:
            assert totalFollowed == results["artists"]["total"]

        for item in results["artists"]["items"]:
            artist = Artist(item["id"], item["name"], item["popularity"])
            res.append(artist)
            i += 1

    return res


def get_new_tracks(spotifyAccessPublic, spotifyAccessPrivate, period):
    periodStart = datetime.datetime.utcnow() - period
    def is_current(album):
        return album.release_date > periodStart
    def get_album_release_date(album):
        return album.release_date

    res = []
    # Iterate over followed artists:
    for artist in get_followed_artists(spotifyAccessPrivate):
        # Sort albums by release date to get tracks from their first released album:
        albums = sorted(artist.get_albums_with_tracks(spotifyAccessPublic), key=get_album_release_date)
        foundTrackNames = []
        # Iterate over albums of artist:
        for album in albums:
            # Iterate over tracks in album and filter tracks from artist:
            for track in album.tracks:
                if not track.name in foundTrackNames:
                    foundTrackNames.append(track.name)

                    if is_current(album) and not track.album.is_collection() and track.is_done_by_artist(artist.id):
                        res.append((artist, track))
    return res


##
# Implementations of the main commands:
##


def update_release_radar(clientId, clientSecret, period):
    def get_track_release_date(track):
        return track.album.release_date
    def get_track_id(track):
        return track.id

    logging.info("Updating playlist Release Radar...")

    logging.debug("Connecting to Spotify...")
    accessScopes = ["user-follow-read", "playlist-modify-private", "playlist-read-private"]
    redirectUri = "http://127.0.0.1:9090"
    spotifyAccessPrivate = spotipy.Spotify(auth_manager=SpotifyOAuth(client_id=clientId, client_secret=clientSecret, redirect_uri=redirectUri, scope=accessScopes))
    spotifyAccessPublic = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=clientId, client_secret=clientSecret))
    logging.info("Connected to Spotify.")
    
    # Get current user:
    logging.debug("Requesting current user...")
    currentUserId = spotifyAccessPrivate.current_user()["id"]
    logging.debug("Received current user.")

    # Make sure the playlist "Release Radar" exists and get current content:
    releaseRadarPLId = None
    logging.debug("Requesting first page of user playlists...")
    resultPart = spotifyAccessPrivate.user_playlists(currentUserId)
    logging.debug("Received first page of user playlists.")
    while resultPart:
        for playlist in resultPart['items']:
            if playlist["name"] == "Release Radar":
                releaseRadarPLId = playlist["id"]
                resultPart = None
                break
        if resultPart != None and resultPart['next']:
            logging.debug("Requesting next page of user playlists...")
            resultPart = spotifyAccessPrivate.next(resultPart)
            logging.debug("Received next page of user playlists.")
        else:
            resultPart = None

    if not releaseRadarPLId:
        logging.debug("Creating new playlists...")
        creationResult = spotifyAccessPrivate.user_playlist_create(
                currentUserId,
                "Release Radar",
                public=False,
                collaborative=False,
                description="Automatically generated list of new releases of followed artists.")
        logging.debug("Created new playlists.")
        releaseRadarPLId = creationResult["id"]

    # Determine new tracks and make sure all ids are unique:
    logging.debug("Determining unique new track IDs:")
    newUniqueTracks = []
    for (artist, track) in get_new_tracks(spotifyAccessPublic, spotifyAccessPrivate, period):
        if not track.id in map(get_track_id, newUniqueTracks):
            newUniqueTracks.append(track)

    # Sort tracks by release date:
    newUniqueTracks.sort(key=get_track_release_date, reverse=False)

    # Add new tracks to playlist:
    logging.debug("Replace tracks of playlist...")
    addResult = spotifyAccessPrivate.playlist_replace_items(releaseRadarPLId, map(get_track_id, newUniqueTracks))
    if "snapshot_id" in addResult:
        logging.info("Successfully added new releases to playlist.")
    else:
        logging.error("Could not replace tracks of playlist.")


def print_new_albums(clientSecret, clientId, period):
    logging.info("Printing new albums:")

    periodStart = datetime.datetime.utcnow() - period
    def is_current(album):
        return album.release_date > periodStart

    logging.debug("Connecting to Spotify...")
    accessScopes = ["user-follow-read", "playlist-modify-private", "playlist-read-private"]
    redirectUri = "http://127.0.0.1:9090"
    spotifyAccessPrivate = spotipy.Spotify(auth_manager=SpotifyOAuth(client_id=clientId, client_secret=clientSecret, redirect_uri=redirectUri, scope=accessScopes))
    spotifyAccessPublic = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=clientId, client_secret=clientSecret))
    logging.debug("Connected to Spotify.")

    for artist in get_followed_artists(spotifyAccessPrivate):
        print(artist.name + ":")
        for album in artist.get_albums(spotifyAccessPublic):
            if is_current(album) and not track.album.is_collection() and track.is_done_by_artist(artist.id):
                print(album.release_date.strftime("%Y-%m-%d") + " " + album.name)
        print()


def set_operation(parsed_args, client_id, client_secret, operation):
    logging.debug("Connecting to Spotify...")
    accessScopes = ["playlist-modify-private", "playlist-read-private"]
    redirectUri = "http://127.0.0.1:9090"
    spotifyAccess = spotipy.Spotify(auth_manager=SpotifyOAuth(client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirectUri,
        scope=accessScopes))
    logging.debug("Connected to Spotify.")

    input_sets = []
    for playlist_name in parsed_args.in_playlist:
        playlist = Playlist.by_name(spotifyAccess, playlist_name)
        if playlist == None:
            logging.error("There is no playlist with name " + playlist_name)
            return
        else:
            input_sets.append(set(playlist.get_tracks(spotifyAccess)))

    target_playlist = Playlist.by_name(spotifyAccess, parsed_args.result)
    if target_playlist == None:
        target_playlist = Playlist.create_playlist(spotifyAccess, parsed_args.result)

    resulting_set = operation(spotifyAccess, input_sets)
    target_playlist.update_tracks(spotifyAccess, resulting_set)


def union(spotifyAccess, input_sets):
    union_set = set()
    for l in input_sets:
        union_set = union_set.union(l)

    return union_set

def intersection(spotifyAccess, input_sets):
    result_set = input_sets[0]
    for l in input_sets[1:]:
        result_set = result_set.intersection(l)

    return result_set



##
# Functions to handle user input:
##


def parse_args(args):
    parser = argparse.ArgumentParser(
            description="Advanced libary handling for spotify.")

    parser.add_argument("-d", "--debug",
            action="store_true",
            help="enable debugging output")
    subcmd_parsers = parser.add_subparsers(help="Commands", dest="command")

    update_parser = subcmd_parsers.add_parser("update",
            help="update playlists automatically")
    update_parser.add_argument("target",
            action="store",
            choices=["Release Radar"],
            help="the playlist to update")
    update_parser.add_argument("-d", "--days",
            action="store",
            required=False,
            type=int,
            default=8,
            help="max age of added titles in days")
    
    show_parser = subcmd_parsers.add_parser("show",
            help="display possible updates for playlists")
    show_parser.add_argument("target",
            action="store",
            choices=["Release Radar"],
            help="the playlist to update")

    union_parser = subcmd_parsers.add_parser("union",
            help="create the union of playlists")
    union_parser.add_argument("-p", "--in_playlist",
            action="append",
            required=True,
            help="a playlists to take as input")
    union_parser.add_argument("result",
            action="store",
            help="the playlist to save the union to")

    intersection_parser = subcmd_parsers.add_parser("intersection",
            help="create the intersection of playlists")
    intersection_parser.add_argument("-p", "--in_playlist",
            action="append",
            required=True,
            help="a playlists to take as input")
    intersection_parser.add_argument("result",
            action="store",
            help="the playlist to save the intersection to")


    return parser.parse_args(args)


def get_client_creds():
    clientId=""
    if "SPOTIFY_CLIENT_ID" in os.environ:
        clientId = os.environ["SPOTIFY_CLIENT_ID"]
    else:
        clientId = getpass.getpass(prompt="Client ID: ", stream=None)
    clientSecret = ""
    if "SPOTIFY_CLIENT_SECRET" in os.environ:
        clientSecret = os.environ["SPOTIFY_CLIENT_SECRET"]
    else:
        clientSecret = getpass.getpass(prompt="Client secret: ", stream=None)

    return (clientId, clientSecret)



debugging = False

try:
    parsed = parse_args(sys.argv[1:])

    (clientId, clientSecret) = get_client_creds()

    if parsed.debug:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")
    else:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if parsed.command == "update":
        period = datetime.timedelta(days=parsed.days)
        update_release_radar(clientId, clientSecret, period=period)

    elif parsed.command == "show":
        period = datetime.timedelta(days=parsed.days)
        print_new_albums(clientId, clientSecret, period=period)

    elif parsed.command == "union":
        set_operation(parsed, clientId, clientSecret, union)

    elif parsed.command == "intersection":
        set_operation(parsed, clientId, clientSecret, intersection)


except KeyboardInterrupt:
    logging.warning("Keyboard interrupt: Ending query early.")
    exit()

logging.info("Done.")
