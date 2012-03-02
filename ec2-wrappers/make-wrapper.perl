#!/usr/bin/perl
use warnings;
use strict;
use Cwd 'abs_path';

my $script = abs_path(shift);
my $short_name = shift;

print "Create PRIVILLEGE ELEVATING wrapper for $script called $short_name?";
chomp(my $answer = <STDIN>);
die unless $answer eq 'yes';
my $wrapper = "/home/ff/cs61c/bin/$short_name";
open my $out, '>', $wrapper or die $!;
print $out <<'EOF';
#!/usr/bin/perl -T
use warnings;
use strict;
chdir '/' or die "chdir: $!\n";
%ENV = (
    PATH => '/bin:/usr/bin',
    PYTHONPATH => '/home/ff/cs61c/ec2-wrappers:/home/ff/cs61c/lib/python',
    REAL_USERNAME => scalar getpwuid($<),
);
die "Must use cs61c account\n" unless $ENV{REAL_USERNAME} =~ /^cs61c/;
EOF

print $out "exec '$script', \@ARGV;\n";
print $out <<'EOF';
die "exec: $!\n";
EOF

close $out;

chmod 04755, $out or die "chmod: $!\n";
