#!/usr/bin/perl
use warnings;
use strict;
use FindBin '$Bin';
use lib "$Bin/lib";
use HTTP::Proxy ':log';
use HTTP::Proxy::BodyFilter::htmlparser;
use HTTP::Proxy::HeaderFilter::simple;
use HTML::Entities;

my ($socks_port, $http_port, $default_url) = @ARGV;

$socks_port ||= 8889;
$http_port ||= 8888;

my $proxy = HTTP::Proxy->new( port => $http_port);


$proxy->push_filter(request => RewriteRequests->new);

my $parser = HTML::Parser->new( 
    api_version => 3,
    start_h => [\&start_tag, 'self, tagname, attr, text'],
    default_h => [\&misc_tag, 'self, text'],
);

$proxy->push_filter(
    mime => 'text/html',
    response => HTTP::Proxy::BodyFilter::htmlparser->new(
        $parser, rw => 1,
    ),
);

my $fix_redirects = HTTP::Proxy::HeaderFilter::simple->new(
    sub {
        my ($self, $headers, $message) = @_;
        return unless $headers->header('Location');
        my $uri = URI->new($headers->header('Location'));
        return unless $uri->scheme eq 'http';
        my $fixed_path = "/" . $uri->host . "/" . $uri->port . $uri->path;
        my $orig_uri = $proxy->stash('orig_uri');
        $headers->header('Location' =>
            "http://" . $orig_uri->host . ':' . $orig_uri->port . $fixed_path
        );
    }
);

$proxy->push_filter(response => $fix_redirects);

$proxy->init;

$proxy->agent->proxy('http' => "socks://localhost:$socks_port");

$proxy->agent->protocols_allowed(['http', 'socks']);

# $proxy->logmask(ALL);

$proxy->start;

exit;

sub start_tag {
    my ($self, $tag, $attrs, $text) = @_;
    my $base_uri = $self->{message}->base;
    for my $uri_attr (qw(href src)) {
        next unless exists $attrs->{$uri_attr};
        my $uri = URI->new_abs($attrs->{$uri_attr}, $base_uri);
        my $fixed_uri = "/" . $uri->host . "/" . $uri->port . $uri->path;
        $fixed_uri .= $uri->query ? '?' . $uri->query : '';
        $attrs->{$uri_attr} = $fixed_uri;
    }
    $_ = encode_entities($_) for values %$attrs;
    $_[0]->{output} .= "<$tag " . join(" ", map {"$_='" . $attrs->{$_} . "'"} keys %$attrs) . ">";
}

sub misc_tag {
    $_[0]->{output} .= $_[1];
}

package RewriteRequests;

use base 'HTTP::Proxy::HeaderFilter';

sub filter {
    my ($self, $headers, $message) = @_;

    $proxy->stash('orig_uri' => $message->uri);

    my $old_uri = $message->uri;
    my(undef,$server,$port,$rest) = split '/', $old_uri->path, 4;
    $rest ||= '';
    if ($server eq 'favicon.ico') {
        $server = '';
        $port = '';
        $rest = '/favicon.ico';
    }
    $rest .= $old_uri->query ? '?' . $old_uri->query : '';
    if ($server eq '') {
        $message->uri($default_url . $rest)
    } else {
        if ($port eq '80') {
            $message->uri(
                URI->new("http://$server/$rest")
            );
        } else {
            $message->uri(
                URI->new("http://$server:$port/$rest")
            )
        }
    }
    $headers->header('Host' => undef);
}

