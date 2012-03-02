#line 1 "HTTP/Proxy/Engine.pm"
package HTTP::Proxy::Engine;
use strict;
use Carp;

my %engines = (
    MSWin32 => 'NoFork',
    default => 'Legacy',
);

# required accessors
__PACKAGE__->make_accessors( qw( max_clients ));

sub new {
    my $class  = shift;
    my %params = @_;

    # the front-end
    if ( $class eq 'HTTP::Proxy::Engine' ) {
        my $engine = delete $params{engine};
        $engine = $engines{$^O} || $engines{default}
          unless defined $engine;

        $class = "HTTP::Proxy::Engine::$engine";
        eval "require $class";
        croak $@ if $@;
    }

    # some error checking
    croak "No proxy defined"
      unless exists $params{proxy};
    croak "$params{proxy} is not a HTTP::Proxy object"
      unless UNIVERSAL::isa( $params{proxy}, 'HTTP::Proxy' );

    # so we are an actual engine
    no strict 'refs';
    return bless {
        %{"$class\::defaults"},
        %params
    }, $class;
}

# run() should be defined in subclasses
sub run {
    my $self = shift;
    my $class = ref $self;
    croak "$class doesn't define a run() method";
}

sub proxy { $_[0]{proxy} }

# class method
sub make_accessors {
    my $class = shift;

    for my $attr (@_) {
        no strict 'refs';
        *{"$class\::$attr"} = sub {
            $_[0]{$attr} = $_[1] if defined $_[1];
            $_[0]{$attr};
        };
    }
}

1;

__END__

#line 184

