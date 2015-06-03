#  Copyright (C) 2015  Hannes H Loeffler
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#
#  For full details of the license please see the COPYING file
#  that should have come with this distribution.

r'''
Generates CHARMM prm, psf and cord files from AMBER parmtop and inpcrd.
Only the extended format is supported but CMAP and CHEQ are not.
'''

__revision__ = "$Id$"



import os, math

import Sire.IO
import Sire.MM

from FESetup import const, errors, logger


prefix = 'G'
num_prefix = 'X'



def _check_type(s):
    """Check atom types."""

    if any(c.islower() for c in s):
      s = prefix + s.upper()
    elif not s[0].isalpha():
      s = num_prefix + s.upper()

    return s



class CharmmTop(object):
    """Basic CHARMM prm and psf writer."""

    def __init__(self):
        self.atoms = []
        self.bonds = []
        self.angles = []
        self.dihedrals = []
        self.impropers = []
        self.groups = []

        self.atom_params = {}
        self.bond_params = {}
        self.angle_params = {}
        self.dihedral_params = {}
        self.improper_params = {}
        self.nonbonded_params = []


    def readParm(self, parmtop, inpcrd):
        """
        Extract topology and coordinate information from AMBER parmtop and
        inpcrd.  Store data internally.

        :param parmtop: parmtop file name
        :type parmtop: string
        :param inpcrd: inpcrd file name
        :type inprcd: string
        :raises: SetupError
        """

        amber = Sire.IO.Amber()

        try:
            # (Sire.Mol.Molecules,  Sire.Vol.PeriodicBox or Sire.Vol.Cartesian)
            mols, perbox = amber.readCrdTop(inpcrd, parmtop)
        except UserWarning as error:
            raise errors.SetupError('error opening %s/%s' % (parmtop, inpcrd) )

        try:
            dims = perbox.dimensions() # Sire.Maths.Vector

            x = dims.x()
            y = dims.y()
            z = dims.z()
        except:                         # FIXME: which exception?
            x, y, z = 0.0, 0.0, 0.0

        self.box_dims = x, y, z

        mol_numbers = mols.molNums()
        mol_numbers.sort()

        self.tot_natoms = sum(mols.at(num).molecule().nAtoms()
                              for num in mol_numbers)

        segcnt = ord('A') - 1
        atomno = 0
        offset = 0

        for num in mol_numbers:
            mol = mols.at(num).molecule()
            natoms = mol.nAtoms()
            segcnt += 1

            for atom in mol.atoms():
                atomno += 1
                residue = atom.residue()
                resno = residue.number().value()
                res = str(residue.name().value() )
                atom_type = str(atom.name().value() )
                amber_type = str(atom.property('ambertype') )
                resid = str(resno)  # FIXME
                charge = atom.property('charge').value()
                mass = atom.property('mass').value()
                lj = atom.property('LJ')
                coords = atom.property('coordinates')

                # FIXME: water name, large segments
                if residue.name().value() == 'WAT':
                    segid = 'W'  # FIXME
                    res = 'TIP3'
                else:
                    segid = chr(segcnt)  # FIXME: check for overflow

                amber_type = _check_type(amber_type)

                self.atoms.append( (atomno, resno, segid, resid, res, atom_type,
                                    amber_type, charge, mass, coords) )
                self.atom_params[amber_type] = (mass, lj)


            params = mol.property('amberparameters') # Sire.Mol.AmberParameters

            for bond in params.getAllBonds():  # Sire.Mol.BondID
                at0 = bond.atom0()  # Sire.Mol.AtomIdx!
                at1 = bond.atom1()

                name0 = _check_type(str(mol.select(at0).property('ambertype')))
                name1 = _check_type(str(mol.select(at1).property('ambertype')))
                k, r = params.getParams(bond)

                self.bonds.append( (at0.value() + 1 + offset,
                               at1.value() + 1 + offset) )
                self.bond_params[name0, name1] = (k, r)

            self.bonds.sort()

            for angle in params.getAllAngles():  # Sire.Mol.AngleID
                at0 = angle.atom0()  # Sire.Mol.AtomIdx!
                at1 = angle.atom1()
                at2 = angle.atom2()
                k, theta = params.getParams(angle)

                name0 = _check_type(str(mol.select(at0).property('ambertype')))
                name1 = _check_type(str(mol.select(at1).property('ambertype')))
                name2 = _check_type(str(mol.select(at2).property('ambertype')))

                self.angles.append( (at0.value() + 1 + offset,
                                     at1.value() + 1 + offset,
                                     at2.value() + 1 + offset) )
                self.angle_params[name0, name1, name2] = (k, theta * const.RAD2DEG)

            self.angles.sort()

            for dihedral in params.getAllDihedrals(): # Sire.Mol.DihedralID
                at0 = dihedral.atom0()  # Sire.Mol.AtomIdx!
                at1 = dihedral.atom1()
                at2 = dihedral.atom2()
                at3 = dihedral.atom3()

                name0 = _check_type(str(mol.select(at0).property('ambertype')))
                name1 = _check_type(str(mol.select(at1).property('ambertype')))
                name2 = _check_type(str(mol.select(at2).property('ambertype')))
                name3 = _check_type(str(mol.select(at3).property('ambertype')))

                p = params.getParams(dihedral)
                terms = []

                n = 3
                for i in range(0, len(p), n):       # k, np, phase
                    terms.append(p[i:i+n])

                self.dihedrals.append( (at0.value() + 1 + offset,
                                        at1.value() + 1 + offset,
                                        at2.value() + 1 + offset,
                                        at3.value() + 1 + offset) )

                self.dihedral_params[name0, name1, name2, name3] = terms

            self.dihedrals.sort()

            for improper in params.getAllImpropers():
                at0 = improper.atom0()
                at1 = improper.atom1()
                at2 = improper.atom2()
                at3 = improper.atom3()

                name0 = _check_type(str(mol.select(at0).property('ambertype')))
                name1 = _check_type(str(mol.select(at1).property('ambertype')))
                name2 = _check_type(str(mol.select(at2).property('ambertype')))
                name3 = _check_type(str(mol.select(at3).property('ambertype')))

                term = params.getParams(improper)

                self.impropers.append( (at0.value() + 1 + offset,
                                   at1.value() + 1 + offset,
                                   at2.value() + 1 + offset,
                                   at3.value() + 1 + offset) )

                self.improper_params[name0, name1, name2, name3] = term

            self.impropers.sort()

            # groups: base pointer charge type (1=neutral,2=charged),
            #         entire group fixed?
            for residue in mol.residues():
                charge = 0.0
                first = True

                for atom in residue.atoms():
                    if first:
                        gp_base = atom.index().value() + offset
                        first = False

                    charge += atom.property('charge').value()

                if charge > 0.01: # FIXME
                    gp_type = 2
                else:
                    gp_type = 1

                self.groups.append( (gp_base, gp_type) )

            offset += natoms


    def writeCrd(self, filename):
        """Write crd coordinate file.

* Expanded format for more than 100000 atoms (upto 10**10) and with
up to 8 character PSF IDs. (versions c31a1 and later)
         title
         NATOM (I10)
         ATOMNO RESNO   RES  TYPE  X     Y     Z   SEGID RESID Weighting
           I10   I10 2X A8 2X A8       3F20.10     2X A8 2X A8 F20.10

           :param filename: output file name for cord file
           :type filename: string
         """

        fmt = '%10i%10i  %-8s  %-8s%20.10f%20.10f%20.10f  %-8s  %-8s%20.10f\n'
        weight = 0.0

        with open(filename, 'w') as crd:
            crd.write('* Created by FESetup\n*\n%10i  EXT\n' % self.tot_natoms)

            for atom in self.atoms:
                crd.write(fmt % (atom[0], atom[1], atom[4], atom[5], atom[9][0],
                                 atom[9][1], atom[9][2], atom[2], atom[3],
                                 weight) )
                
                
                #crd.write(fmt % (atomno, resno, res, atom_type, coords[0],
                #                 coords[1], coords[2], segid, resid,
                #                 weight) )


    def writePrmPsf(self, rtfname, prmname, psfname):
        """Write prm and psf files.

        ATOM                             (Flexible paramters only)
         MASS   code   type   mass       (Flexible paramters only)

        EQUIvalence                      (Flexible paramters only)
         group  atom [ repeat(atom) ]    (Flexible paramters only)

        BOND
         atom atom force_constant distance

        ANGLe or THETA
         atom atom atom force_constant theta_min UB_force_constant UB_rmin

        DIHE or PHI
         atom atom atom atom force_constant periodicity phase

        IMPRoper or IMPHI
         atom atom atom atom force_constant periodicity phase

        NBONd or NONB  [nonbond-defaults]
         atom* polarizability  e  vdW_radius -
              [1-4 polarizability  e  vdW_radius]

        NBFIX
         atom_i* atom_j*  emin rmin [ emin14 [ rmin14 ]]

         :param rtfname: output file name for RTF file
         :type rtfname: string
         :param prmname: output file name for PRM file
         :type prmname: string
         :param psfname: output file name for PSF file
         :type psfname: string
        """

        with open(psfname, 'w') as psf:
            psf.write('PSF EXT\n\n'
                      '        1 !NTITLE\n'
                      '* Created by FESetup\n'
                      '\n%10i !NATOM\n' %
                      self.tot_natoms)

            # I10,1X,A8,1X,A8,1X,A8,1X,A8,1X,A6,1X,2G14.6,I8,2G14.6
            afmt = '%10i %-8s %-8s %-8s %-8s %-6s %14.6f%14.6f%8i\n'

            for atom in self.atoms:
                psf.write(afmt % (atom[0], atom[2], atom[3], atom[4], atom[5],
                                  atom[6], atom[7], atom[8], 0.0) )

            l = len(self.bonds)
            psf.write('\n%10i !NBOND\n' % l)

            for i, bp in enumerate(self.bonds):
                psf.write('%10i%10i' % (bp[0], bp[1]) )

                if not (i + 1) % 4:
                    psf.write('\n')

            if (i + 1) % 4 or l < 1:
                psf.write('\n')

            l = len(self.angles)
            psf.write('\n%10i !NTHETA\n' % l)
    
            for i, at in enumerate(self.angles):
                psf.write('%10i%10i%10i' % (at[0], at[1], at[2]) )

                if not (i + 1) % 3:
                    psf.write('\n')

            if (i + 1) % 3 or l < 1:
                psf.write('\n')

            l = len(self.dihedrals)
            psf.write('\n%10i !NPHI\n' % l)
    
            for i, dq in enumerate(sorted(self.dihedrals) ):
                psf.write('%10i%10i%10i%10i' % (dq[0], dq[1], dq[2], dq[3]) )

                if not (i + 1) % 2:
                    psf.write('\n')

            if (i + 1) % 2 or l < 1:
                psf.write('\n')


            l = len(self.impropers)
            psf.write('\n%10i !NIMPHI\n' % l)
    
            for i, dq in enumerate(self.impropers):
                psf.write('%10i%10i%10i%10i' % (dq[0], dq[1], dq[2], dq[3]) )

                if not (i + 1) % 2:
                    psf.write('\n')

            if (i + 1) % 2 or l < 1:
                psf.write('\n')

            psf.write('\n%10i !NDON\n\n\n%10i !NACC\n\n' % (0, 0) )
            psf.write('\n%10i !NNB\n\n' % 0)

            # iblo (exclusion pointer): one entry for each atom
            for i in range(0, self.tot_natoms):
               psf.write('%10i' % 0)

               if not (i + 1) % 8:
                    psf.write('\n')

            if (i + 1) % 8:
                psf.write('\n')

            l = len(self.groups)
            psf.write('\n%10i%10i !NGRP NST2\n' % (l, 0) )

            for i, group in enumerate(self.groups):
                psf.write('%10i%10i%10i' % (group[0], group[1], 0) )

                if not (i + 1) % 3:
                    psf.write('\n')

            if (i + 1) % 3 or l < 1:
                psf.write('\n')

            psf.write('\n%10i%10i !NUMLP NUMLPH\n' % (0, 0) )


        with open(rtfname, 'w') as prm:
            prm.write('* created by FESetup\n'
                      '* minimal RTF\n'
                      '*\n'
                      '36 1\n\n')

            atomno = 0

            for atom, param in self.atom_params.iteritems():
                atomno += 1
                prm.write('MASS %5i %-6s %9.5f\n' % (atomno, atom, param[0]) )

            prm.write('\nEND\n')

        with open(prmname, 'w') as prm:
            prm.write('* created by FESetup\n*\n')

            prm.write('\nATOMS\n')

            atomno = 0

            for atom, param in self.atom_params.iteritems():
                atomno += 1
                prm.write('MASS %5i %-6s %9.5f\n' % (atomno, atom, param[0]) )

            prm.write('\nBONDS\n')
            visited = set()

            for n, p in self.bond_params.iteritems():
                visited.add(n)

                if n[0] == n[1] or (n[1], n[0]) not in visited:
                    prm.write('%-6s %-6s %7.2f %10.4f\n' % (n[0], n[1],
                                                            p[0], p[1]) )

            prm.write('\nANGLES\n')
            prm.write('HW  OW  HW  100.0  104.52 !TIP3P water\n'
                      'OW  HW  HW    0.0  127.74 !TIP3P water\n')
            visited = set()

            for n, p in self.angle_params.iteritems():
                visited.add(n)

                if n[0] == n[2] or (n[2], n[1], n[0]) not in visited:
                    prm.write('%-6s %-6s %-6s %7.2f %10.4f\n' %
                              (n[0], n[1], n[2], p[0], p[1]) )

            prm.write('\nDIHEDRALS\n')
            visited = set()

            for n, terms in self.dihedral_params.iteritems():
                visited.add(n)

                if n[0] == n[3] or (n[3], n[2], n[1], n[0]) not in visited:
                    for term in terms:
                        prm.write('%-6s %-6s %-6s %-6s %10.4f %4i %10.4f\n' %
                                  (n[0], n[1], n[2], n[3],
                                   term[0], term[1], term[2] * const.RAD2DEG) )

            prm.write('\nIMPROPER\n')
            visited = set()

            for n, term in self.improper_params.iteritems():
                visited.add(n)

                if n[0] == n[3] or (n[3], n[2], n[1], n[0]) not in visited:
                    prm.write('%-6s %-6s %-6s %-6s %10.4f %4i %10.4f\n' %
                              (n[0], n[1], n[2], n[3],
                               term[0], term[1], term[2] * const.RAD2DEG) )

            prm.write('''
NONBONDED  NBXMOD 5  GROUP SWITCH CDIEL -
     CUTNB 14.0  CTOFNB 12.0  CTONNB 10.0  EPS 1.0  E14FAC 0.83333333  WMIN 1.4
''')
            for atom, param in self.atom_params.iteritems():
                epsilon = -param[1].epsilon().value()
                sigma = param[1].sigma().value() * const.RSTAR_CONV

                # FIXME: support other scalings too? but only one scale factor
                #        electrostatic factor for electrostatics!
                prm.write('%-6s %3.1f %9.6f %9.4f %3.1f %9.6f %9.4f\n' %
                          (atom, 0.0, epsilon, sigma,
                                 0.0, epsilon / 2.0, sigma) )

            prm.write('\nEND\n')


    def unwrap(self, coords, boxx, boxy, boxz):
        """
        Unwrap coordinates because Gromacs uses atom-based wrapping.

        The current code assumes largest molecule is not larger than the
        box minus an arbitrary buffer.  Possible alternative: check all
        bonds an move atom if bond length is larger than half the box
        length.

        :param coords: flat list of coordinates
        :type coords: list
        :param boxx: box dimension in x direction
        :type boxx: float
        :param boxy: box dimension in y direction
        :type boxy: float
        :param boxz: box dimension in z direction
        :type boxz: float
        """

        pass



if __name__ == '__main__':
    import sys

    nargs = len(sys.argv)

    if nargs != 3:
        sys.exit('Usage: %s prmtop inpcrd' % sys.argv[0])


    top = CharmmTop()
    top.readParm(sys.argv[1], sys.argv[2])
    top.writeCrd('test.cor')            # vmd expects cor for CHARMM ASCII
    top.writePrmPsf('test.rtf', 'test.prm', 'test.psf')
 