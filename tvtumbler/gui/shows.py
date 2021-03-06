'''
This file is part of TvTumbler.

Created on Sep 21, 2013

@author: Dermot Buckley
@copyright: Copyright (c) 2013, Dermot Buckley
@license: GPL
@contact: info@tvtumbler.com
'''
import os
import sys
import threading
import time
import traceback

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from .. import quality, logger
from ..comms.client import service_api
from .actions import *
from .common import TvTumblerWindowXMLDialog
from .contextmenu import ContextMenuDialog


__addon__ = xbmcaddon.Addon()
__addonpath__ = __addon__.getAddonInfo('path').decode('utf-8')


class TvTumblerShows(TvTumblerWindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.shows = None
        self._shows_lock = threading.Lock()
        self._slow_show_data_loader = None

    def onInit(self):
        try:
            self._show_loading_dialog()
            if not self.check_service_ok():
                self._hide_loading_dialog()
                self.close()
                return

            self._update_loading_dialog(25, 'Creating slow data loader...')
            self._slow_show_data_loader = threading.Thread(target=self._load_slow_show_data, name='slow_show_data_loader')
            self._slow_show_data_loader._abort = False
            self._slow_show_data_loader.start()
            with self._shows_lock:
                self._update_loading_dialog(50, 'Loading TV Shows ...')
                self.shows = service_api.get_all_shows(properties=['tvshowid', 'name', 'tvdb_id',
                                                                   'followed', 'wanted_quality', 'fast_status'])
                # logger.debug(repr(self.shows))
                self._update_loading_dialog(75, 'Displaying TV Shows ...')
                self.updateDisplay()

            self._update_loading_dialog(85, 'Running Basic Checks ...')
            if len(self.shows) == 0:
                self._update_loading_dialog(0)
                dlg = xbmcgui.Dialog()
                dlg.ok('TvTumbler', 'No TV Shows Found!', 'Click OK to add a TV Show')
                if not self.add_show():
                    self.close()
                    return

            non_xbmc_shows = [s for s in self.shows if ('tvshowid' not in s or s['tvshowid'] is None)]
            # if we have even one non xbmc show (i.e not in the library), then we must
            # ensure a valid download path
            if len(non_xbmc_shows):
                if not self.ensure_valid_download_dir():
                    self._update_loading_dialog(0)
                    self.close()
                    return

            self._update_loading_dialog(95, 'Completing ...')
            self.getControl(120).selectItem(0)  # select the first row
            self.setFocus(self.getControl(120))
        except Exception, e:
            logger.error(e)
            logger.error(traceback.format_exc)
        self._hide_loading_dialog()

    def _load_slow_show_data(self):
        start_time = time.time()
        xbmc.sleep(1000)  # give the gui a chance to draw
        count = 0
        while not self.shows:
            logger.debug('Waiting for fast data to finish, this should not usually happen')
            count = count + 1
            xbmc.sleep(300)
            if count > 100:
                logger.notice('timeout in _load_slow_show_data waiting for fast data.  giving up')
                return
        with self._shows_lock:
            remaining_tvdb_ids = [str(s['tvdb_id']) for s in self.shows]
        num_at_a_time = 2
        while remaining_tvdb_ids:
            lookup_this_time = remaining_tvdb_ids[:num_at_a_time]
            remaining_tvdb_ids = remaining_tvdb_ids[num_at_a_time:]
            if (self._slow_show_data_loader._abort or xbmc.abortRequested):
                logger.debug('thread aborting')
                return
            more_data = service_api.get_shows(tvdb_ids=lookup_this_time,
                                              properties=['tvdb_id', 'poster', 'fanart',
                                                          'banner', 'thumbnail', 'status'])
            d = {}
            for s in more_data:
                # we index on tvdb_id for ease of lookup
                d[str(s['tvdb_id'])] = s

            logger.debug('got slow data: ' + repr(more_data))

            with self._shows_lock:
                for s in self.shows:
                    if str(s['tvdb_id']) in d:
                        s.update(d[str(s['tvdb_id'])])  # copy everything from slow entry into fast one

            lctrl = self.getControl(120)
            for i in range(0, lctrl.size()):
                item = lctrl.getListItem(i)
                tvdb_id = item.getProperty('tvdb_id')
                if tvdb_id in d:
                    show = d[tvdb_id]

                    for img_pref in ['fanart', 'poster', 'banner', 'thumbnail']:
                        if img_pref in show and show[img_pref]:
                            item.setProperty('image', show[img_pref])
                            break
                    if 'status' in show and show['status']:
                        logger.debug('setting status property to %s' % (repr(show['status'])))
                        item.setProperty('status', show['status'])

                    # small hack here: we need to change some standard property of
                    # the ListItem to ensure that it redraws.  The easiest way to do that
                    # is to change label
                    item.setLabel(item.getLabel() + ' ')

            if remaining_tvdb_ids:
                xbmc.sleep(50)  # allow a screen refresh

        end_time = time.time()

        logger.debug('Slow show data finished loading.  Time takes %f seconds' % (end_time - start_time))

    def onClick(self, controlId):
        pass

    def onFocus(self, controlId):
        logger.debug('onFocus(' + str(controlId) + ')')
        self.controlId = controlId

    def onAction(self, action):
        logger.debug("ACTION: " + str(action.getId()) + " FOCUS: " +
                     str(self.getFocusId()) + " BC: " + str(action.getButtonCode()))
        if action == ACTION_CONTEXT_MENU:
            self.doMenu()
        elif action == ACTION_SELECT_ITEM:
            if self.getFocusId() == 205:  # follow/ignore button
                self.toggleFollow()
            elif self.getFocusId() == 120:  # select a line on the list itself
                self.toggleFollow()
            elif self.getFocusId() == 200:
                self.add_show()
            elif self.getFocusId() == 201:
                self.do_downloads()
            elif self.getFocusId() == 202:
                self.openSettings()
            else:
                pass
                # self.eplist()
        elif action == ACTION_PARENT_DIR:
            action = ACTION_PREVIOUS_MENU
        elif action == ACTION_MOUSE_LEFT_CLICK:
            if self.getFocusId() == 205:  # follow/ignore button
                self.toggleFollow()
            elif self.getFocusId() == 120:  # click a line on the list itself
                self.toggleFollow()
            elif self.getFocusId() == 200:
                self.add_show()
            elif self.getFocusId() == 201:
                self.do_downloads()
            elif self.getFocusId() == 202:
                self.openSettings()

        if (action == ACTION_PREVIOUS_MENU and
            self._slow_show_data_loader and
            self._slow_show_data_loader.is_alive()):
                self._slow_show_data_loader._abort = True
        xbmcgui.WindowXMLDialog.onAction(self, action)

    def openSettings(self):
        __addon__.openSettings()
        # self.loadSettings()

    def do_downloads(self):
        from .downloads import TvTumblerDownloads
        if self._slow_show_data_loader and self._slow_show_data_loader.is_alive():
            self._slow_show_data_loader._abort = True
        w = TvTumblerDownloads('script-tvtumbler-downloads.xml', __addonpath__, "Default")
        # self.close()
        w.doModal()
        del w

    def add_show(self):
        keyboard = xbmc.Keyboard('', 'Search for Show', False)
        keyboard.doModal()
        while (keyboard.isConfirmed()):
            searchstring = keyboard.getText()
            if searchstring:
                choices = service_api.search_series_by_name(searchstring=searchstring)
                logger.debug('got choices: ' + repr(choices))
                dlg = xbmcgui.Dialog()
                if not choices:
                    dlg.ok('TvTumbler', 'No matching series found')
                    keyboard.doModal()
                    continue
                options = []
                for c in choices:
                    label = ''
                    if 'seriesname' in c:
                        label = label + c['seriesname']
                    else:
                        continue # just skip anythign that doesn't have a name
                    if 'network' in c:
                        label = label + ' [' + c['network'] + ']'
                    if 'firstaired' in c:
                        label = label + ' (Started: %s)' % (c['firstaired'],)
                    if 'seriesid' not in c:
                        continue

                    options.append((label, c['seriesid']))
                selected = dlg.select('Possible Matches', [o[0] for o in options])
                if selected >= 0:
                    tvdb_id = options[selected][1]
                    logger.debug('Request to add show: ' + repr(tvdb_id))
                    if service_api.add_show(tvdb_id=options[selected][1], followed=True):
                        show_data = service_api.get_shows(tvdb_ids=[tvdb_id],
                                                          properties=['tvshowid', 'name', 'tvdb_id',
                                                                      'followed', 'wanted_quality',
                                                                      'status', 'fanart'])
                        self.shows.extend(show_data)
                        self.updateDisplay()
                        self.select_show(tvdb_id)
                        return True
                    else:
                        # show didn't add for some reason
                        return False
                else:
                    # they didn't select anything
                    keyboard.doModal()
                    continue
            else:
                # no search term?
                return False

        # they cancelled input
        return False

    def ensure_valid_download_dir(self):
        new_show_path = __addon__.getSetting('new_show_path')
        if (new_show_path is None or
            new_show_path == '' or
            not xbmcvfs.exists(new_show_path)):

            # we need to prompt them for a valid download path
            dlg = xbmcgui.Dialog()
            dlg.ok('TvTumbler', 'Directory for New TV Shows is not set', 'Click OK to set it now.')
            try:
                path = dlg.browse(3,  # type: ShowAndGetWriteableDirectory
                                  'Select Directory for New Shows',  # heading:
                                  'video'
                                  )
            except:
                # the above will give a RuntimeError if there is no video library set up.  So use this instead.
                path = dlg.browse(3,  # type: ShowAndGetWriteableDirectory
                                  'Select Directory for New Shows',  # heading:
                                  'files'
                                  )
            logger.debug('got path: "%s"' % (path,))
            if path and xbmcvfs.exists(path):
                __addon__.setSetting('new_show_path', path)
                return True
            else:
                # they cancelled the dialog
                return False
        else:
            # path is ok
            return True

    def doMenu(self):
        item, show = self._get_selected_item_and_show()
        options = []
        if item:
            if show['followed']:
                options.append(('Ignore', self.toggleFollow))
                options.append(('Select Quality', self.select_wanted_quality))
            else:
                options.append(('Follow', self.toggleFollow))
        else:
            # we have no non-item menu items
            pass

        if options:
            selected = ContextMenuDialog.select([o[0] for o in options])
            if selected is not None:
                options[selected][1]()

    def _get_selected_item_and_show(self):
        item = self.getControl(120).getSelectedItem()
        if not item:
            logger.debug('no show selected')
            return None
        tvdb_id = item.getProperty('tvdb_id')
        show = [s for s in self.shows if str(s['tvdb_id']) == str(tvdb_id)][0]
        return item, show

    def select_wanted_quality(self):
        item, show = self._get_selected_item_and_show()
        if not item:
            logger.notice('Attempt to set wanted quality with no item selected!')
            return
        followed = show['followed']
        if not followed:
            dlg = xbmcgui.Dialog()
            dlg.ok('TvTumbler', 'Not Following', 'You are not following this show currently.',
                   'Unable to set wanted quality.')
            return

        qualities_available = ['SD', 'HD', 'Any']
        selected_quality = ContextMenuDialog.select(qualities_available)
        if selected_quality is None:
            return

        real_quality_values = [quality.SD_COMP, quality.HD_COMP, quality.ANY]
        real_quality = real_quality_values[selected_quality]
        logger.debug('setting wanted quality for %s to %s' % (str(show['tvdb_id']), str(real_quality)))
        service_api.set_show_wanted_quality(tvdb_id=show['tvdb_id'], wanted_quality=real_quality)
        show['wanted_quality'] = real_quality
        item.setProperty('wanted_quality', str(show['wanted_quality']))
        item.setProperty('wanted_quality_str', self.str_from_quality(show['wanted_quality']))

    def toggleFollow(self):
        item = self.getControl(120).getSelectedItem()
        if not item:
            return
        tvdb_id = item.getProperty('tvdb_id')
        show = [s for s in self.shows if str(s['tvdb_id']) == str(tvdb_id)][0]
        current_value = show['followed']
        new_value = not current_value
        logger.debug('changing followed for %s from %s to %s' % (str(tvdb_id), repr(current_value), repr(new_value)))
        service_api.set_show_followed(tvdb_id=tvdb_id, followed=new_value)

        if new_value:
            # if we are telling the server to follow, then the server may change the wanted_quality to a valid value.
            # We need to refresh to get it.
            show['wanted_quality'] = service_api.get_show_wanted_quality(tvdb_id=tvdb_id)

        item.setLabel2('Follow' if new_value else 'Ignore')
        # item.setProperty('Genre', 'followed' if new_value else 'Ignored')
        item.setProperty('follow', 'true' if new_value else 'false')
        item.setProperty('wanted_quality', str(show['wanted_quality']))
        item.setProperty('wanted_quality_str', self.str_from_quality(show['wanted_quality']))
        show['followed'] = new_value

    @staticmethod
    def str_from_quality(qual):
        if qual == 0 or qual is None:
            return 'None'
        elif qual in quality.quality_strings:
            return quality.quality_strings[qual]
        else:
            return 'Custom'

    def select_show(self, tvdb_id):
        '''
        Select a show from the listctrl by tvdb_id.
        
        @param tvdb_id:
        @type tvdb_id:
        '''
        lctrl = self.getControl(120)
        for i in range(0, lctrl.size()):
            item = lctrl.getListItem(i)
            if item.getProperty('tvdb_id') == str(tvdb_id):
                lctrl.selectItem(i)
                return True
        return False

    def updateDisplay(self):
        pass
        disp = {}
        for show in self.shows:
            # trim off a leading 'the' if there is one
            if show['name'].lower().startswith('the '):
                disp[show['name'][4:]] = show
            else:
                disp[show['name']] = show
        sortd = disp.keys()
        sortd.sort()
        self.getControl(120).reset()
        for k in sortd:
            show = disp[k]
            item = xbmcgui.ListItem(label=show['name'], label2='Follow' if show['followed'] else 'Ignore')
            item.setProperty('follow', 'true' if show['followed'] else 'false')
            item.setProperty('wanted_quality', str(show['wanted_quality']))
            item.setProperty('wanted_quality_str', self.str_from_quality(show['wanted_quality']))
            for img_pref in ['fanart', 'poster', 'banner', 'thumbnail']:
                if img_pref in show and show[img_pref]:
                    item.setProperty('image', show[img_pref])
                    break
            if 'status' in show and show['status']:
                item.setProperty('status', str(show['status']))
            elif 'fast_status' in show and show['fast_status']:
                item.setProperty('status', str(show['fast_status']))
            item.setProperty('tvdb_id', str(show['tvdb_id']))
            item.setInfo('video', {'sorttitle': k})  # we set this so that we can use numpad letters to navigate
            self.getControl(120).addItem(item)
#         if self.jump_to_bottom: self.getControl(120).selectItem(self.getControl(120).size() - 1)
