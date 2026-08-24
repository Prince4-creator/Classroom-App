import socket
host='db.puqdlbvzcnvmqrfvorsw.supabase.co'
print('Resolving host:', host)
try:
    addrs6 = socket.getaddrinfo(host, None, socket.AF_INET6)
    print('AAAA records (IPv6):')
    for a in addrs6:
        print(' ', a[4][0])
except Exception as e:
    print('No IPv6:', e)
try:
    addrs4 = socket.getaddrinfo(host, None, socket.AF_INET)
    print('A records (IPv4):')
    for a in addrs4:
        print(' ', a[4][0])
except Exception as e:
    print('No IPv4:', e)
