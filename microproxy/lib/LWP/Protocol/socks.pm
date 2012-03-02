#line 1 "LWP/Protocol/socks.pm"
##############################
package LWP::Protocol::http::socks;
require LWP::Protocol::http;
our @ISA = qw(LWP::Protocol::http);
our $VERSION = "1.3";
LWP::Protocol::implementor('http::socks' => 'LWP::Protocol::http::socks');

sub new {
    my $self = shift->SUPER::new(@_);
    $self->{scheme} =~ s/::socks$//;
    $self;
}

sub _extra_sock_opts {
    my $self = shift;
    my($host, $port) = @_;
    my @extra_sock_opts = $self->SUPER::_extra_sock_opts(@_);
    #(@extra_sock_opts, SocksDebug =>1, @{$self->{proxy_sock_opts}});
    (@extra_sock_opts, @{$self->{proxy_sock_opts}});
}

##############################
package LWP::Protocol::http::socks::Socket;
require LWP::Protocol::http;
require IO::Socket::Socks;
require Net::HTTP;
our @ISA = qw(LWP::Protocol::http::SocketMethods IO::Socket::Socks Net::HTTP);

sub configure {
    my $self = shift;
    my $args = shift;

    my $connectAddr = $args->{ConnectAddr} = delete $args->{PeerAddr};
    my $connectPort = $args->{ConnectPort} = delete $args->{PeerPort};

    $self->SUPER::configure($args);
    $self->http_configure($args);
}

##############################
package LWP::Protocol::https::socks;
require LWP::Protocol::https;
our @ISA = qw(LWP::Protocol::https);
LWP::Protocol::implementor('https::socks' => 'LWP::Protocol::https::socks');

sub new {
    my $self = shift->SUPER::new(@_);
    $self->{scheme} =~ s/::socks$//;
    $self;
}

sub _extra_sock_opts {
    my $self = shift;
    my($host, $port) = @_;
    my @extra_sock_opts = $self->SUPER::_extra_sock_opts(@_);
    (@extra_sock_opts, @{$self->{proxy_sock_opts}});
    #(@extra_sock_opts, @{$self->{proxy_sock_opts}});
}

##############################
package LWP::Protocol::https::socks::Socket;
require LWP::Protocol::https;
require IO::Socket::Socks;
use IO::Socket::SSL;
require Net::HTTPS;
our @ISA = qw(IO::Socket::SSL LWP::Protocol::https::Socket);

sub new {
    my $class = shift;
    my %args = @_;
    my $connectAddr = $args{ConnectAddr} = delete $args{PeerAddr};
    my $connectPort = $args{ConnectPort} = delete $args{PeerPort};
    my $socks = new IO::Socket::Socks(%args);
    $args{PeerAddr} = $connectAddr;
    $args{PeerPort} = $connectPort;
    delete $args{ProxyAddr};
    delete $args{ProxyPort};
    delete $args{ConnectAddr};
    delete $args{ConnectPort};
    my $ssl = new_from_fd LWP::Protocol::https::socks::Socket($socks, %args);
    $ssl->http_configure(\%args);
    $ssl;
}

# hack out the connect so it doesn't reconnect
sub http_connect {
    1;
}

##############################
package LWP::Protocol::socks;
require LWP::Protocol;
our @ISA = qw(LWP::Protocol);

sub request {
    my($self, $request, $proxy, $arg, $size, $timeout) = @_;
    my $url = $request->uri;
    my $scheme = $url->scheme;

    my $protocol = LWP::Protocol::create("$scheme\::socks", $self->{ua});
    $protocol->{proxy_sock_opts} = [ProxyAddr => $proxy->host,
				    ProxyPort => $proxy->port,
				    ];

    # [RT 48172] Adding user/pass functionality
    if ( $proxy->userinfo() ) {
	push(@{$protocol->{proxy_sock_opts}},
	     AuthType => 'userpass',
	     Username => $proxy->user(),
	     Password => $proxy->pass(),
	    );
    }

    $protocol->request($request, undef, $arg, $size, $timeout);
}

1;

__END__

#line 161