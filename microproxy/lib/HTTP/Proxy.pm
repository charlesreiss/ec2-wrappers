#line 1 "HTTP/Proxy.pm"
package HTTP::Proxy;

use HTTP::Daemon;
use HTTP::Date qw(time2str);
use LWP::UserAgent;
use LWP::ConnCache;
use Fcntl ':flock';         # import LOCK_* constants
use IO::Select;
use Sys::Hostname;          # hostname()
use Carp;

use strict;
use vars qw( $VERSION $AUTOLOAD @METHODS
             @ISA @EXPORT @EXPORT_OK %EXPORT_TAGS );

require Exporter;
@ISA    = qw(Exporter);
@EXPORT = ();               # no export by default
@EXPORT_OK = qw( ERROR NONE    PROXY  STATUS PROCESS SOCKET HEADERS FILTERS
                 DATA  CONNECT ENGINE ALL );
%EXPORT_TAGS = ( log => [@EXPORT_OK] );    # only one tag

$VERSION = '0.24';

my $CRLF = "\015\012";                     # "\r\n" is not portable

# standard filters
use HTTP::Proxy::HeaderFilter::standard;

# constants used for logging
use constant ERROR   => -1;    # always log
use constant NONE    => 0;     # never log
use constant PROXY   => 1;     # proxy information
use constant STATUS  => 2;     # HTTP status
use constant PROCESS => 4;     # sub-process life (and death)
use constant SOCKET  => 8;     # low-level connections
use constant HEADERS => 16;    # HTTP headers
use constant FILTERS => 32;    # Messages from filters
use constant DATA    => 64;    # Data received by the filters
use constant CONNECT => 128;   # Data transmitted by the CONNECT method
use constant ENGINE  => 256;   # Internal information from the Engine
use constant ALL     => 511;   # All of the above

# modules that need those constants to be defined
use HTTP::Proxy::Engine;
use HTTP::Proxy::FilterStack;

# Methods we can forward
my %METHODS;

# HTTP (RFC 2616)
$METHODS{http} = [qw( CONNECT DELETE GET HEAD OPTIONS POST PUT TRACE )];

# WebDAV (RFC 2518)
$METHODS{webdav} = [
    @{ $METHODS{http} },
    qw( COPY LOCK MKCOL MOVE PROPFIND PROPPATCH UNLOCK )
];

# Delta-V (RFC 3253)
$METHODS{deltav} = [
    @{ $METHODS{webdav} },
    qw( BASELINE-CONTROL CHECKIN CHECKOUT LABEL MERGE MKACTIVITY
        MKWORKSPACE REPORT UNCHECKOUT UPDATE VERSION-CONTROL ),
];

# the whole method list
@METHODS = HTTP::Proxy->known_methods();

# useful regexes (from RFC 2616 BNF grammar)
my %RX;
$RX{token}  = qr/[-!#\$%&'*+.0-9A-Z^_`a-z|~]+/;
$RX{mime}   = qr($RX{token}/$RX{token});
$RX{method} = '(?:' . join ( '|', @METHODS ) . ')';
$RX{method} = qr/$RX{method}/;

sub new {
    my $class  = shift;
    my %params = @_;

    # some defaults
    my %defaults = (
        agent    => undef,
        chunk    => 4096,
        daemon   => undef,
        host     => 'localhost',
        logfh    => *STDERR,
        logmask  => NONE,
        max_connections => 0,
        max_keep_alive_requests => 10,
        port     => 8080,
        stash    => {},
        timeout  => 60,
        via      => hostname() . " (HTTP::Proxy/$VERSION)",
        x_forwarded_for => 1,
    );

    # non modifiable defaults
    my $self = bless { conn => 0, loop => 1 }, $class;

    # support for deprecated stuff
    {
        my %convert = (
            maxchild => 'max_clients',
            maxconn  => 'max_connections',
            maxserve => 'max_keep_alive_requests',
        );
        while( my ($old, $new) = each %convert ) {
            if( exists $params{$old} ) {
               $params{$new} = delete $params{$old};
               carp "$old is deprecated, please use $new";
            }
        }
    }

    # get attributes
    $self->{$_} = exists $params{$_} ? delete( $params{$_} ) : $defaults{$_}
      for keys %defaults;

    # choose an engine with the remaining parameters
    $self->{engine} = HTTP::Proxy::Engine->new( %params, proxy => $self );
    $self->log( PROXY, "PROXY", "Selected engine " . ref $self->{engine} );

    return $self;
}

sub known_methods {
    my ( $class, @args ) = @_;

    @args = map { lc } @args ? @args : ( keys %METHODS );
    exists $METHODS{$_} || carp "Method group $_ doesn't exist"
        for @args;
    my %seen;
    return grep { !$seen{$_}++ } map { @{ $METHODS{$_} || [] } } @args;
}

sub timeout {
    my $self = shift;
    my $old  = $self->{timeout};
    if (@_) {
        $self->{timeout} = shift;
        $self->agent->timeout( $self->{timeout} ) if $self->agent;
    }
    return $old;
}

sub url {
    my $self = shift;
    if ( not defined $self->daemon ) {
        carp "HTTP daemon not started yet";
        return undef;
    }
    return $self->daemon->url;
}

# normal accessors
for my $attr ( qw(
    agent chunk daemon host logfh port request response hop_headers
    logmask via x_forwarded_for client_headers engine
    max_connections max_keep_alive_requests
    )
  )
{
    no strict 'refs';
    *{"HTTP::Proxy::$attr"} = sub {
        my $self = shift;
        my $old  = $self->{$attr};
        $self->{$attr} = shift if @_;
        return $old;
      }
}

# read-only accessors
for my $attr (qw( conn loop client_socket )) {
    no strict 'refs';
    *{"HTTP::Proxy::$attr"} = sub { $_[0]{$attr} }
}

sub max_clients { shift->engine->max_clients( @_ ) }

# deprecated methods are still supported
{
    my %convert = (
        maxchild => 'max_clients',
        maxconn  => 'max_connections',
        maxserve => 'max_keep_alive_requests',
    );
    while ( my ( $old, $new ) = each %convert ) {
        no strict 'refs';
        *$old = sub {
            carp "$old is deprecated, please use $new";
            goto \&$new;
        };
    }
}

sub stash {
    my $stash = shift->{stash};
    return $stash unless @_;
    return $stash->{ $_[0] } if @_ == 1;
    return $stash->{ $_[0] } = $_[1];
}

sub new_connection { ++$_[0]{conn} }

sub start {
    my $self = shift;

    $self->init;
    $SIG{INT} = $SIG{TERM} = sub { $self->{loop} = 0 };

    # the main loop
    my $engine = $self->engine;
    $engine->start if $engine->can('start');
    while( $self->loop ) {
        $engine->run;
        last if $self->max_connections && $self->conn >= $self->max_connections;
    }
    $engine->stop if $engine->can('stop');

    $self->log( STATUS, "STATUS",
        "Processed " . $self->conn . " connection(s)" );

    return $self->conn;
}

# semi-private init method
sub init {
    my $self = shift;

    # must be run only once
    return if $self->{_init}++;

    $self->_init_daemon if ( !defined $self->daemon );
    $self->_init_agent  if ( !defined $self->agent );

    # specific agent config
    $self->agent->requests_redirectable( [] );
    $self->agent->agent('');    # for TRACE support
    $self->agent->protocols_allowed( [qw( http https ftp gopher )] );

    # standard header filters
    $self->{headers}{request}  = HTTP::Proxy::FilterStack->new;
    $self->{headers}{response} = HTTP::Proxy::FilterStack->new;

    # the same standard filter is used to handle headers
    my $std = HTTP::Proxy::HeaderFilter::standard->new();
    $std->proxy( $self );
    $self->{headers}{request}->push(  [ sub { 1 }, $std ] );
    $self->{headers}{response}->push( [ sub { 1 }, $std ] );

    # standard body filters
    $self->{body}{request}  = HTTP::Proxy::FilterStack->new(1);
    $self->{body}{response} = HTTP::Proxy::FilterStack->new(1);

    return;
}

#
# private init methods
#

sub _init_daemon {
    my $self = shift;
    my %args = (
        LocalAddr => $self->host,
        LocalPort => $self->port,
        ReuseAddr => 1,
    );
    delete $args{LocalPort} unless $self->port;    # 0 means autoselect
    my $daemon = HTTP::Daemon->new(%args)
      or die "Cannot initialize proxy daemon: $!";
    $self->daemon($daemon);

    return $daemon;
}

sub _init_agent {
    my $self  = shift;
    my $agent = LWP::UserAgent->new(
        env_proxy  => 1,
        keep_alive => 2,
        parse_head => 0,
        timeout    => $self->timeout,
      )
      or die "Cannot initialize proxy agent: $!";
    $self->agent($agent);
    return $agent;
}

# This is the internal "loop" that lets the child process process the
# incoming connections.

sub serve_connections {
    my ( $self, $conn ) = @_;
    my $response;
    $self->{client_socket} = $conn;  # read-only
    $self->log( SOCKET, "SOCKET", "New connection from " . $conn->peerhost
                      . ":" . $conn->peerport );

    my ( $last, $served ) = ( 0, 0 );

    while ( $self->loop() ) {
        my $req;
        {
            local $SIG{INT} = local $SIG{TERM} = 'DEFAULT';
            $req = $conn->get_request();
        }

        $served++;

        # initialisation
        $self->request($req);
        $self->response(undef);

        # Got a request?
        unless ( defined $req ) {
            $self->log( ERROR, "ERROR",
                "Getting request failed: " . $conn->reason )
                if $conn->reason ne 'No more requests from this connection';
            return;
        }
        $self->log( STATUS, "REQUEST", $req->method . ' '
           . ( $req->method eq 'CONNECT' ? $req->uri->host_port : $req->uri ) );

        # can we forward this method?
        if ( !grep { $_ eq $req->method } @METHODS ) {
            $response = HTTP::Response->new( 501, 'Not Implemented' );
            $response->content_type( "text/plain" );
            $response->content(
                "Method " . $req->method . " is not supported by this proxy." );
            $self->response($response);
            goto SEND;
        }

        # transparent proxying support
        if( not defined $req->uri->scheme ) {
            if( my $host = $req->header('Host') ) {
                 $req->uri->scheme( 'http' );
                 $req->uri->host( $host );
            }
            else {
                $response = HTTP::Response->new( 400, 'Bad request' );
                $response->content_type( "text/plain" );
                $response->content("Can't do transparent proxying without a Host: header.");
                $self->response($response);
                goto SEND;
            }
        }

        # can we serve this protocol?
        if ( !$self->is_protocol_supported( my $s = $req->uri->scheme ) )
        {
            # should this be 400 Bad Request?
            $response = HTTP::Response->new( 501, 'Not Implemented' );
            $response->content_type( "text/plain" );
            $response->content("Scheme $s is not supported by this proxy.");
            $self->response($response);
            goto SEND;
        }

        # select the request filters
        $self->{$_}{request}->select_filters( $req ) for qw( headers body );

        # massage the request
        $self->{headers}{request}->filter( $req->headers, $req );

        # FIXME I don't know how to get the LWP::Protocol objet...
        # NOTE: the request is always received in one piece
        $self->{body}{request}->filter( $req->content_ref, $req, undef );
        $self->{body}{request}->eod;    # end of data
        $self->log( HEADERS, "REQUEST", $req->headers->as_string );

        # CONNECT method is a very special case
        if( ! defined $self->response and $req->method eq 'CONNECT' ) {
            $last = $self->_handle_CONNECT($served);
            return if $last;
        }

        # the header filters created a response,
        # we won't contact the origin server
        # FIXME should the response header and body be filtered?
        goto SEND if defined $self->response;

        # FIXME - don't forward requests to ourselves!

        # pop a response
        my ( $sent, $chunked ) = ( 0, 0 );
        $response = $self->agent->simple_request(
            $req,
            sub {
                my ( $data, $response, $proto ) = @_;

                # first time, filter the headers
                if ( !$sent ) { 
                    $sent++;
                    $self->response( $response );
                    
                    # select the response filters
                    $self->{$_}{response}->select_filters( $response )
                      for qw( headers body );

                    $self->{headers}{response}
                         ->filter( $response->headers, $response );
                    ( $last, $chunked ) =
                      $self->_send_response_headers( $served );
                }

                # filter and send the data
                $self->log( DATA, "DATA",
                    "got " . length($data) . " bytes of body data" );
                $self->{body}{response}->filter( \$data, $response, $proto );
                if ($chunked) {
                    printf $conn "%x$CRLF%s$CRLF", length($data), $data
                      if length($data);    # the filter may leave nothing
                }
                else { print $conn $data; }
            },
            $self->chunk
        );

        # remove the header added by LWP::UA before it sends the response back
        $response->remove_header('Client-Date');

        # do a last pass, in case there was something left in the buffers
        my $data = "";    # FIXME $protocol is undef here too
        $self->{body}{response}->filter_last( \$data, $response, undef );
        if ( length $data ) {
            if ($chunked) {
                printf $conn "%x$CRLF%s$CRLF", length($data), $data;
            }
            else { print $conn $data; }
        }

        # last chunk
        print $conn "0$CRLF$CRLF" if $chunked;    # no trailers either
        $self->response($response);

        # the callback is not called by LWP::UA->request
        # in some case (HEAD, error)
        if ( !$sent ) {
            $self->response($response);
            $self->{$_}{response}->select_filters( $response )
              for qw( headers body );
            $self->{headers}{response}
                 ->filter( $response->headers, $response );
        }

        # what about X-Died and X-Content-Range?
        if( my $died = $response->header('X-Died') ) {
            $self->log( ERROR, "ERROR", $died );
            $sent = 0;
            $response = HTTP::Response->new( 500, "Proxy filter error" );
            $response->content_type( "text/plain" );
            $response->content($died);
            $self->response($response);
        }

      SEND:

        $response = $self->response ;

        # responses that weren't filtered through callbacks
        # (empty body or error)
        # FIXME some error response headers might not be filtered
        if ( !$sent ) {
            ($last, $chunked) = $self->_send_response_headers( $served );
            my $content = $response->content;
            if ($chunked) {
                printf $conn "%x$CRLF%s$CRLF", length($content), $content
                  if length($content);    # the filter may leave nothing
                print $conn "0$CRLF$CRLF";
            }
            else { print $conn $content; }
        }

        # FIXME ftp, gopher
        $conn->print( $response->content )
          if defined $req->uri->scheme
             and $req->uri->scheme =~ /^(?:ftp|gopher)$/
             and $response->is_success;

        $self->log( SOCKET, "SOCKET", "Connection closed by the proxy" ), last
          if $last || $served >= $self->max_keep_alive_requests;
    }
    $self->log( SOCKET, "SOCKET", "Connection closed by the client" )
      if !$last
      and $served < $self->max_keep_alive_requests;
    $self->log( PROCESS, "PROCESS", "Served $served requests" );
    $conn->close;
}

# INTERNAL METHOD
# send the response headers for the proxy
# expects $served  (number of requests served)
# returns $last and $chunked (last request served, chunked encoding)
sub _send_response_headers {
    my ( $self, $served ) = @_;
    my ( $last, $chunked ) = ( 0, 0 );
    my $conn = $self->client_socket;
    my $response = $self->response;

    # correct headers
    $response->remove_header("Content-Length")
      if $self->{body}{response}->will_modify();
    $response->header( Server => "HTTP::Proxy/$VERSION" )
      unless $response->header( 'Server' );
    $response->header( Date => time2str(time) )
      unless $response->header( 'Date' );

    # this is adapted from HTTP::Daemon
    if ( $conn->antique_client ) { $last++ }
    else {
        my $code = $response->code;
        $conn->send_status_line( $code, $response->message,
            $self->request()->protocol() );
        if ( $code =~ /^(1\d\d|[23]04)$/ ) {

            # make sure content is empty
            $response->remove_header("Content-Length");
            $response->content('');
        }
        elsif ( $response->request && $response->request->method eq "HEAD" )
        {    # probably OK, says HTTP::Daemon
        }
        else {
            if ( $conn->proto_ge("HTTP/1.1") ) {
                $chunked++;
                $response->push_header( "Transfer-Encoding" => "chunked" );
                $response->push_header( "Connection"        => "close" )
                  if $served >= $self->max_keep_alive_requests;
            }
            else {
                $last++;
                $conn->force_last_request;
            }
        }
        print $conn $response->headers_as_string($CRLF);
        print $conn $CRLF;    # separates headers and content
    }
    $self->log( STATUS,  "RESPONSE", $response->status_line );
    $self->log( HEADERS, "RESPONSE", $response->headers->as_string );
    return ($last, $chunked);
}

# INTERNAL method
# FIXME no man-in-the-middle for now
sub _handle_CONNECT {
    my ($self, $served) = @_;
    my $last = 0;

    my $conn = $self->client_socket;
    my $req  = $self->request;
    my $upstream;

    # connect upstream
    if ( my $up = $self->agent->proxy('http') ) {

        # clean up authentication info from proxy URL
        $up =~ s{^http://[^/\@]*\@}{http://};

        # forward to upstream proxy
        $self->log( PROXY, "PROXY",
            "Forwarding CONNECT request to next proxy: $up" );
        my $response = $self->agent->simple_request($req);

        # check the upstream proxy's response
        my $code = $response->code;
        if ( $code == 407 ) {    # don't forward Proxy Authentication requests
            my $response_407 = $response->as_string;
            $response_407 =~ s/^Client-.*$//mg;
            $response = HTTP::Response->new(502);
            $response->content_type("text/plain");
            $response->content( "Upstream proxy ($up) "
                    . "requested authentication:\n\n"
                    . $response_407 );
            $self->response($response);
            return $last;
        }
        elsif ( $code != 200 ) {    # forward every other failure
            $self->response($response);
            return $last;
        }

        $upstream = $response->{client_socket};
    }
    else {                                  # direct connection
        $upstream = IO::Socket::INET->new( PeerAddr => $req->uri->host_port );
    }

    # no upstream socket obtained
    if( !$upstream ) {
        my $response = HTTP::Response->new( 500 );
        $response->content_type( "text/plain" );
        $response->content( "CONNECT failed: $@");
        $self->response($response);
        return $last;
    }

    # send the response headers (FIXME more headers required?)
    my $response = HTTP::Response->new(200);
    $self->response($response);
    $self->{$_}{response}->select_filters( $response ) for qw( headers body );

    $self->_send_response_headers( $served );

    # we now have a TCP connection
    $last = 1;

    my $select = IO::Select->new;
    for ( $conn, $upstream ) {
         $_->autoflush(1);
         $_->blocking(0);
         $select->add($_);
    }

    # loop while there is data
    while ( my @ready = $select->can_read ) {
        for (@ready) {
            my $data = "";
            my ($sock, $peer, $from ) = $conn eq $_
                                      ? ( $conn, $upstream, "client" )
                                      : ( $upstream, $conn, "server" );

            # read the data
            my $read = $sock->sysread( $data, 4096 );
          
            # check for errors
            if(not defined $read ) {
                $self->log( ERROR, "CONNECT", "Read undef from $from ($!)" );
                next;
            }

            # end of connection
            if ( $read == 0 ) {
                $_->close for ( $sock, $peer );
                $select->remove( $sock, $peer );
                $self->log( SOCKET, "CONNECT", "Connection closed by the $from" );
                $self->log( PROCESS, "PROCESS", "Served $served requests" );
                next;
            }

            # proxy the data
            $self->log( CONNECT, "CONNECT", "$read bytes received from $from" );
            $peer->syswrite($data, length $data);
        }
    }
    $self->log( CONNECT, "CONNECT", "End of CONNECT proxyfication");
    return $last;
}

sub push_filter {
    my $self = shift;
    my %arg  = (
        mime   => 'text/*',
        method => join( ',', @METHODS ),
        scheme => 'http',
        host   => '',
        path   => '',
        query  => '',
    );

    # parse parameters
    for( my $i = 0; $i < @_ ; $i += 2 ) {
        next if $_[$i] !~ /^(mime|method|scheme|host|path|query)$/;
        $arg{$_[$i]} = $_[$i+1];
        splice @_, $i, 2;
        $i -= 2;
    }
    croak "Odd number of arguments" if @_ % 2;

    # the proxy must be initialised
    $self->init;

    # prepare the variables for the closure
    my ( $mime, $method, $scheme, $host, $path, $query ) =
      @arg{qw( mime method scheme host path query )};

    if ( defined $mime && $mime ne '' ) {
        $mime =~ m!/! or croak "Invalid MIME type definition: $mime";
        $mime =~ s/\*/$RX{token}/;    #turn it into a regex
        $mime = qr/^$mime(?:$|\s*;?)/;
    }

    my @method = split /\s*,\s*/, $method;
    for (@method) { croak "Invalid method: $_" if !/$RX{method}/ }
    $method = @method ? '(?:' . join ( '|', @method ) . ')' : '';
    $method = qr/^$method$/;

    my @scheme = split /\s*,\s*/, $scheme;
    for (@scheme) {
        croak "Unsupported scheme: $_"
          if !$self->is_protocol_supported($_);
    }
    $scheme = @scheme ? '(?:' . join ( '|', @scheme ) . ')' : '';
    $scheme = qr/$scheme/;

    $host  ||= '.*'; $host  = qr/$host/i;
    $path  ||= '.*'; $path  = qr/$path/;
    $query ||= '.*'; $query = qr/$query/;

    # push the filter and its match method on the correct stack
    while(@_) {
        my ($message, $filter ) = (shift, shift);
        croak "'$message' is not a filter stack"
          unless $message =~ /^(request|response)$/;

        croak "Not a Filter reference for filter queue $message"
          unless ref( $filter )
          && ( $filter->isa('HTTP::Proxy::HeaderFilter')
            || $filter->isa('HTTP::Proxy::BodyFilter') );

        my $stack;
        $stack = 'headers' if $filter->isa('HTTP::Proxy::HeaderFilter');
        $stack = 'body'    if $filter->isa('HTTP::Proxy::BodyFilter');

        # MIME can only match on reponse
        my $mime = $mime;
        undef $mime if $message eq 'request';

        # compute the match sub as a closure
        # for $self, $mime, $method, $scheme, $host, $path
        my $match = sub {
            return 0
              if ( defined $mime )
              && ( $self->response->content_type || '' ) !~ $mime;
            return 0 if ( $self->{request}->method || '' ) !~ $method;
            return 0 if ( $self->{request}->uri->scheme    || '' ) !~ $scheme;
            return 0 if ( $self->{request}->uri->authority || '' ) !~ $host;
            return 0 if ( $self->{request}->uri->path      || '' ) !~ $path;
            return 0 if ( $self->{request}->uri->query     || '' ) !~ $query;
            return 1;    # it's a match
        };

        # push it on the corresponding FilterStack
        $self->{$stack}{$message}->push( [ $match, $filter ] );
        $filter->proxy( $self );
    }
}

sub is_protocol_supported {
    my ( $self, $scheme ) = @_;
    my $ok = 1;
    if ( !$self->agent->is_protocol_supported($scheme) ) {

        # double check, in case a dummy scheme was added
        # to be handled directly by a filter
        $ok = 0;
        $scheme eq $_ && $ok++ for @{ $self->agent->protocols_allowed };
    }
    $ok;
}

sub log {
    my $self  = shift;
    my $level = shift;
    my $fh    = $self->logfh;

    return unless $self->logmask & $level || $level == ERROR;

    my ( $prefix, $msg ) = ( @_, '' );
    my @lines = split /\n/, $msg;
    @lines = ('') if not @lines;

    flock( $fh, LOCK_EX );
    print $fh "[" . localtime() . "] ($$) $prefix: $_\n" for @lines;
    flock( $fh, LOCK_UN );
}

1;

__END__

#line 1370


