# try to use epoll reactor if available
try:
    from twisted.internet import epollreactor
    epollreactor.install()
except:
    pass

from twisted.application.internet import TCPServer
from twisted.application.service import Application
from twisted.web.server import Site
from twisted.internet import reactor

from fiveserver.config import FiveServerConfig, YamlConfig, DatabaseConfig
from fiveserver.protocol import PacketServiceFactory
from fiveserver.protocol import pes5, pes6
from fiveserver.register import RegistrationResource
from fiveserver import storagecontroller, log
from fiveserver import admin, data, logic
import os


application = Application("Fiveserver application")
fsroot = os.environ.get('FSROOT','.')

scfg = YamlConfig(fsroot + '/etc/conf/fiveserver.yaml')
log.setDebug(scfg.Debug)
dbConfig = DatabaseConfig(**scfg.DB)
storageController = storagecontroller.StorageController(
    dbConfig.getReadPool(), dbConfig.getWritePool())

keepAliveManager = storagecontroller.KeepAliveManager(
    storageController, 
    dbConfig.ConnectionPool.keepAliveInterval,
    dbConfig.ConnectionPool.keepAliveQuery)
keepAliveManager.start()

userData = data.UserData(storageController)
profileData = data.ProfileData(storageController)
matchData = data.MatchData(storageController)
profileLogic = logic.ProfileLogic(matchData, profileData)
config = FiveServerConfig(
    scfg, dbConfig, userData, profileData, matchData, profileLogic)

for gameName,port in scfg.GamePorts.iteritems():
    factory = PacketServiceFactory(config)
    factory.protocol = pes5.NewsProtocol
    if hasattr(scfg, 'Greeting'):
        factory.protocol.GREETING['text'] = scfg.Greeting['text']
    if hasattr(scfg, 'ServerName'):
        factory.protocol.SERVER_NAME = scfg.ServerName
    service = TCPServer(port, factory, interface=config.interface)
    service.setServiceParent(application)

for protocol,port in [
        (pes5.MainService,scfg.NetworkServer['mainService']),
        (pes5.NetworkMenuService,scfg.NetworkServer['networkMenuService']),
        (pes5.LoginServicePES5,scfg.NetworkServer['loginService']['pes5']),
        (pes5.LoginServiceWE9,scfg.NetworkServer['loginService']['we9']),
        (pes5.LoginServiceWE9LE,scfg.NetworkServer['loginService']['we9le']),
        ]:
    factory = PacketServiceFactory(config)
    factory.protocol = protocol
    service = TCPServer(port, factory, interface=config.interface)
    service.setServiceParent(application)

# registration web-service
registrationServer = Site(
    RegistrationResource(config,fsroot + '/web'))
service = TCPServer(scfg.WebInterface['port'], registrationServer, interface=config.interface)
service.setServiceParent(application)

class ServerContextFactory:
    def getContext(self):
        from OpenSSL import SSL
        ctx = SSL.Context(SSL.SSLv23_METHOD)
        ctx.use_privatekey_file(
            fsroot + '/%s/serverkey.pem' % adminConfig.KeysDirectory)
        ctx.use_certificate_file(
            fsroot + '/%s/servercert.pem' % adminConfig.KeysDirectory)
        return ctx

adminConfig = YamlConfig(fsroot + '/etc/conf/admin.yaml')

# server admin web-service (HTTPS, authentication)
adminRoot = admin.AdminRootResource(adminConfig, config)
adminRoot.putChild('', adminRoot)
adminRoot.putChild('home', adminRoot)
adminRoot.putChild('xsl', admin.XslResource(adminConfig))
adminRoot.putChild('log', admin.LogResource(adminConfig, config))
adminRoot.putChild('biglog', admin.LogResource(adminConfig, config))
usersResource = admin.UsersResource(adminConfig, config)
adminRoot.putChild('users', usersResource)
usersResource.putChild(
    'online', admin.UsersOnlineResource(adminConfig, config))
adminRoot.putChild('stats', admin.StatsResource(adminConfig, config))
adminRoot.putChild('profiles', admin.ProfilesResource(adminConfig, config))
adminRoot.putChild(
    'userlock', admin.UserLockResource(adminConfig, config))
adminRoot.putChild(
    'userkill', admin.UserKillResource(adminConfig, config))
adminRoot.putChild('maxusers', admin.MaxUsersResource(adminConfig, config))
adminRoot.putChild('debug', admin.DebugResource(adminConfig, config))
adminRoot.putChild('settings', admin.StoreSettingsResource(adminConfig, config))
adminRoot.putChild('roster', admin.RosterResource(adminConfig, config))
adminRoot.putChild('banned', admin.BannedResource(adminConfig, config))
adminRoot.putChild('ban-add', admin.BanAddResource(adminConfig, config))
adminRoot.putChild(
    'ban-remove', admin.BanRemoveResource(adminConfig, config))
adminRoot.putChild('server-ip', admin.ServerIpResource(adminConfig, config))
adminRoot.putChild('ps', admin.ProcessInfoResource(adminConfig, config))
adminServer = Site(adminRoot)
reactor.listenSSL(adminConfig.AdminPort, adminServer, ServerContextFactory(),
    interface=config.interface)

# stats web-service (HTTP, no authentication)
# Only available for requests from localhost
statsRoot = admin.StatsRootResource(adminConfig, config, False)
statsRoot.putChild('', statsRoot)
statsRoot.putChild('home', statsRoot)
statsRoot.putChild('xsl', admin.XslResource(adminConfig))
usersResource = admin.UsersResource(adminConfig, config, False)
statsRoot.putChild('users', usersResource)
usersResource.putChild(
    'online', admin.UsersOnlineResource(adminConfig, config, False))
statsRoot.putChild('stats', admin.StatsResource(adminConfig, config, False))
statsRoot.putChild(
    'profiles', admin.ProfilesResource(adminConfig, config, False))
statsRoot.putChild('ps', admin.ProcessInfoResource(adminConfig, config, False))
statsServer = Site(statsRoot)
statsService = TCPServer(adminConfig.AdminPort+1, statsServer, 
    interface='127.0.0.1') # restrict to localhost requests only
statsService.setServiceParent(application)
