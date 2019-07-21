#!/usr/bin/env python3
import os
import sys
import json
import time
import argparse
import logging
from urllib.parse import urlparse, parse_qs

# some constants
CONFIG_FILE = 'config.json'
ACTION_REBOOT = 'reboot'
ACTION_BLOCK = 'block'
ACTION_UNBLOCK = 'unblock'

# to get configuration
def getConfigValue(args, name, default=False):

    # check args
    if name in vars(args).keys():
        value = vars(args)[name]
        if value:
            return value

    # check query string
    if 'QUERY_STRING' in os.environ:
        qs = os.environ['QUERY_STRING']
        params = dict(parse_qs(qs))
        if name in params:
            value = params[name]
            if value:
                return value

    # if not found look in config
    config = json.load(open(CONFIG_FILE))
    if name in config:
        value = config[name]

    # fallback to default
    return value if value else default

try:
    from selenium import webdriver
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
except ImportError:
    sys.stderr.write("Error importing selenium - 'pip install selenium'\n")
    raise SystemExit(1)

FORMAT = "[%(asctime)s %(levelname)s] %(message)s"
logging.basicConfig(filename='./netgear-admin.log', filemode='w', level=logging.INFO, format=FORMAT)
logger = logging.getLogger()

# suppress selenium DEBUG logging
selenium_log = logging.getLogger('selenium')
selenium_log.setLevel(logging.INFO)
selenium_log.propagate = True


class NetgearAdmin(object):

    START_URL = 'http://{1}:{2}@{0}/'
    HOME_URL = 'http://{1}:{2}@{0}/ADVANCED_home1.htm'
    BLOCK_URL = 'http://{1}:{2}@{0}/BKS_service.htm'

    def __init__(self, ip, username, password, action, debug=False, browser_name='phantomjs'):
        """
        Initialize class.

        :param username: admin username
        :type username: str
        :param password: admin password
        :type password: str
        :param debug: If true, screenshot all pages
        :type debug: bool
        :param browser_name: Name of the browser to use. Can be one of
        :type browser_name: str
        """
        self.ip = ip
        self.username = username
        self.password = password
        self.action = action
        self.browser_name = browser_name
        self.browser = None
        self._screenshot = debug
        self._screenshot_num = 1
        self.user_agent = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/62.0.3202.62'
        logger.debug('Getting browser instance...')

    def run(self):
        logger.debug('Getting page...')
        try:

            # first connect
            self.browser = self.get_browser()
            self.get_start_page()
            if not self.check_login():
                logger.critical('Login failed')
                self.browser.quit()
                exit(1)

            # reboot
            if self.action == ACTION_REBOOT:
                self.get_home_page()
                self.reboot()

            # block/unblock
            if self.action == ACTION_BLOCK or self.action == ACTION_UNBLOCK:
                self.get_block_page()
                self.block_services(self.action == ACTION_BLOCK)

            # done
            self.browser.quit()

        except Exception:
            if self.browser is not None:
                self.browser.quit()
            raise

    def get_start_page(self):
        self.get(self.START_URL)
        self.wait_for_page_load()
        self.do_screenshot()

    def get_home_page(self):
        self.get(self.HOME_URL)
        self.wait_for_page_load()
        self.do_screenshot()

    def get_block_page(self):
        self.get(self.BLOCK_URL)
        self.wait_for_page_load()
        self.do_screenshot()

    def check_login(self):

        # check multilogin
        try:
            self.browser.find_element_by_xpath("//form[starts-with(@action, 'multi_login.cgi')]")
            logger.info('Multi login warning screen detected')
            self.browser.find_element_by_name('yes').click()
            self.wait_for_page_load()
            self.do_screenshot()
        except:
            logger.debug('No Multi login warning screen detected')
            pass

        # now it should be ok
        try:
            self.browser.find_element_by_name('logout')
            return True
        except:
            logger.debug('Logout button not found')
            return False

    def reboot(self):
        self.browser.find_element_by_id('reboot').click()
        time.sleep(1)
        alert = self.browser.switch_to_alert()
        alert.accept()

    def block_services(self, value):
        apply = self.browser.find_element_by_name('apply')
        radios = self.browser.find_elements_by_name('skeyword')
        for radio in radios:
            attr = radio.get_attribute('value')
            if (value and attr == 'perschedule') or (not value and attr == 'never'):
                logger.info('Clicking "{0}" block option'.format(attr))
                radio.click()
                self.do_screenshot()
                logger.info('Applying block option')
                apply.click()
                time.sleep(1)
                self.wait_for_page_load()
                self.do_screenshot()
                return True
        return False

    def do_screenshot(self):
        """take a debug screenshot"""
        if not self._screenshot:
            return
        fname = os.path.join(
            os.getcwd(), '{n}.png'.format(n=self._screenshot_num)
        )
        self.browser.get_screenshot_as_file(fname)
        logger.debug(
            "Screenshot: {f} of: {s}".format(
                f=fname,
                s=self.browser.current_url
            )
        )
        self._screenshot_num += 1

    def error_screenshot(self, fname=None):
        if fname is None:
            fname = os.path.join(os.getcwd(), 'webdriver_fail.png')
        self.browser.get_screenshot_as_file(fname)
        logger.error("Screenshot saved to: {s}".format(s=fname))
        logger.error("Page title: %s", self.browser.title)
        html_path = os.path.join(os.getcwd(), 'webdriver_fail.html')
        source = self.browser.execute_script(
            "return document.getElementsByTagName('html')[0].innerHTML"
        )
        with codecs.open(html_path, 'w', 'utf-8') as fh:
            fh.write(source)
        logger.error('Page source saved to: %s', html_path)

    def get(self, url):

        url = url.format(self.ip, self.username, self.password)

        """logging wrapper around browser.get"""
        logger.info('GET %s', url)

        self.browser.get(url)
        for x in range(0, 5):
            try:
                WebDriverWait(self.browser, 15).until(
                    lambda x: self.browser.current_url != 'about:blank'
                )
                break
            except Exception:
                logger.warning('GET %s failed; trying again', url)
            self.browser.get(url)
            time.sleep(2)
        else:
            self.error_screenshot()
            raise RuntimeError('GET %s failed' % url)

    def get_browser(self):
        """get a webdriver browser instance """
        if self.browser_name == 'firefox':
            logger.debug("getting Firefox browser (local)")
            if 'DISPLAY' not in os.environ:
                logger.debug("exporting DISPLAY=:0")
                os.environ['DISPLAY'] = ":0"
            browser = webdriver.Firefox()
        elif self.browser_name == 'chrome':
            logger.debug("getting Chrome browser (local)")
            browser = webdriver.Chrome()
        elif self.browser_name == 'chrome-headless':
            logger.debug('getting Chrome browser (local) with --headless')
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            browser = webdriver.Chrome(chrome_options=chrome_options)
        elif self.browser_name == 'phantomjs':
            logger.debug("getting PhantomJS browser (local)")
            dcap = dict(DesiredCapabilities.PHANTOMJS)
            dcap["phantomjs.page.settings.userAgent"] = self.user_agent
            args = [
                '--ssl-protocol=any',
                '--ignore-ssl-errors=true',
                '--web-security=false'
            ]
            browser = webdriver.PhantomJS(
                desired_capabilities=dcap, service_args=args
            )
        else:
            raise SystemExit(
                "ERROR: browser type must be one of 'firefox', 'chrome', "
                "'phantomjs', or 'chrome-headless' not '{b}'".format(
                    b=self.browser_name
                )
            )
        browser.set_window_size(1024, 768)
        logger.debug("returning browser")
        return browser

    def doc_readystate_is_complete(self, _):
        """ return true if document is ready/complete, false otherwise """
        result_str = self.browser.execute_script("return document.readyState")
        if result_str == "complete":
            return True
        return False

    def wait_for_page_load(self, timeout=20):
        """
        Function to wait for page load.

        timeout is in seconds
        """
        self.wait_for_ajax_load(timeout=timeout)
        count = 0
        while len(self.browser.page_source) < 30:
            if count > 20:
                self.error_screenshot()
                raise RuntimeError("Waited 20s for page source to be more "
                                   "than 30 bytes, but still too small...")
            count += 1
            logger.debug('Page source is only %d bytes; sleeping',
                         len(self.browser.page_source))
            time.sleep(1)

    def wait_for_ajax_load(self, timeout=20):
        """
        Function to wait for an ajax event to finish and trigger page load.

        Pieced together from
        http://stackoverflow.com/a/15791319

        timeout is in seconds
        """
        WebDriverWait(self.browser, timeout).until(
            self.doc_readystate_is_complete
        )
        return True

    def wait_by(self, _by, arg, timeout=20):
        """
        Wait for an element By something.
        """
        WebDriverWait(self.browser, timeout).until(
            EC.presence_of_element_located((_by, arg))
        )

def parse_args(argv):
    browsers = ['phantomjs', 'firefox', 'chrome', 'chrome-headless']
    actions = [ACTION_REBOOT, ACTION_BLOCK, ACTION_UNBLOCK]
    p = argparse.ArgumentParser(description='Netgear admin', prog='netgear-admin')
    p.add_argument('-v', '--verbose', dest='verbose', action='count', default=0, help='verbose output. specify twice for debug-level output.')
    p.add_argument('-b', '--browser', dest='browser_name', type=str, default='chrome-headless', choices=browsers, help='Browser name/type to use')
    p.add_argument('-i', '--ip', dest='router_ip', type=str, help='Router IP')
    p.add_argument('-u', '--username', dest='username', type=str, help='Router Username (default is admin)')
    p.add_argument('-p', '--password', dest='password', type=str, help='Router Password')
    p.add_argument('-a', '--action', dest='action', type=str, choices=actions, help='Action to perform')
    args = p.parse_args(argv)
    return args

def set_log_debug():
    set_log_level_format(
        logging.DEBUG,
        "%(asctime)s [%(levelname)s %(filename)s:%(lineno)s - "
        "%(name)s.%(funcName)s() ] %(message)s"
    )

def set_log_level_format(level, format):
    formatter = logging.Formatter(fmt=format)
    logger.handlers[0].setFormatter(formatter)
    logger.setLevel(level)

def main():

    # need to handle cgi too
    isCgi = 'GATEWAY_INTERFACE' in os.environ

    # parse args
    args = parse_args(sys.argv[1:])

    # set logging level
    debug = False
    if args.verbose > 0:
        set_log_debug()
        debug = True

    # get config values
    action = getConfigValue(args, 'action')
    router_ip = getConfigValue(args, 'router_ip')
    username = getConfigValue(args, 'username', 'admin')
    password = getConfigValue(args, 'password')

    # those are required
    if not router_ip or not username or not password:
        msg = 'ERROR: you need to specify router IP, username and password through command line arguments or config.json'
        logger.critical(msg)
        raise SystemExit(msg)
    if not action:
        msg = 'ERROR: you need to specify at least one action to perform'
        logger.critical(msg)
        raise SystemExit(msg)

    # do it
    script = NetgearAdmin(
        router_ip,
        username,
        password,
        action=args.action,
        debug=debug,
        browser_name=args.browser_name
    )
    script.run()

    # cgi requires header
    if isCgi:
        print('Status: 200 OK')
        print('Location: index.html')
        print()

if __name__ == "__main__":
    main()
