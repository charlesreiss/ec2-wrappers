#line 1 "HTTP/Proxy/HeaderFilter.pm"
package HTTP::Proxy::HeaderFilter;

use strict;
use Carp;

sub new {
    my $class = shift;
    my $self = bless {}, $class;
    $self->init(@_) if $self->can('init');
    return $self;
}

sub filter {
    croak "HTTP::Proxy::HeaderFilter cannot be used as a filter";
}

sub proxy {
    my ( $self, $new ) = @_;
    return $new ? $self->{_hphf_proxy} = $new : $self->{_hphf_proxy};
}

1;

__END__

#line 149

